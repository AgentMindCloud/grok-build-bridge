"""Safety audit layer — Bridge's "last line of defence" before deploy.

Two public entry points:

* :func:`scan_generated_code` — runs after the builder produces an agent
  codebase. It combines a fast regex-driven static sweep with a strict
  JSON-mode Grok audit, then merges both results into one
  :class:`SafetyReport`.
* :func:`audit_x_post` — runs right before the bridge publishes anything
  to X. It checks post-length limits and asks Grok for a toxicity /
  accuracy / brand-safety read.

Both honour ``config["safety"]["max_tokens_per_run"]`` so a single scan
cannot burn the token budget, and both surface an ``estimated_cost_usd``
number so operators can see what the audit is costing.

Exceptions are never silently swallowed — any failure inside an LLM call
or JSON parse is wrapped in :class:`BridgeSafetyError` and re-raised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

from grok_build_bridge._console import section, warn
from grok_build_bridge._patterns import STATIC_CHECKS
from grok_build_bridge.xai_client import (
    BridgeRuntimeError,
    ConfigError,
    XAIClient,
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
#
# Prompt-engineering notes:
#
# * We pin ``grok-4.20-0309`` everywhere in this module because it is the
#   cheapest model in ``ALLOWED_MODELS``; safety audits do not benefit from
#   the multi-agent variant and running them through it would triple cost.
# * Every prompt *ends* with "Return ONLY a JSON object..." because models
#   anchor more reliably on the last instruction they see, and JSON-only
#   output is a hard parsing contract downstream.
# * We enumerate the exact JSON keys we want rather than leaving the shape
#   to the model — "freeform JSON" answers drift between calls and break
#   ``json.loads`` at the worst times.
# * The system prompt establishes role + output contract; the user prompt
#   carries the artefact under review. This separation keeps the user
#   content from being misinterpreted as instructions to the model.

_AUDIT_MODEL: Final[str] = "grok-4.20-0309"

_CODE_AUDIT_SYSTEM: Final[str] = (
    "You are a strict code-security auditor for agent codebases that will be "
    "deployed to the X social network. Given a snippet of source code, "
    "identify runtime risks relevant to autonomous agents.\n\n"
    "Audit for: X API abuse (posting loops, reply bombs, follow spam), "
    "rate-limit risk (unbounded request rates, missing backoff), "
    "misinformation risk (hallucinated facts written as truth), "
    "PII exposure (user data leaving the process), "
    "infinite-loop risk (recursion without a termination condition).\n\n"
    "Be terse. Every risk is one short sentence. Do not restate the code."
)

_CODE_AUDIT_USER_TEMPLATE: Final[str] = (
    "Language: {language}\n"
    "--- BEGIN CODE ---\n{code}\n--- END CODE ---\n\n"
    "Return ONLY a JSON object with this exact shape:\n"
    "{{"
    '"risks": [string, ...], '
    '"severity": number between 0 and 1, '
    '"recommendations": [string, ...]'
    "}}"
)

_POST_AUDIT_SYSTEM: Final[str] = (
    "You are a brand-safety reviewer for content that an autonomous agent "
    "is about to publish on X. Review the post for: factual-accuracy "
    "signals, toxicity, rate-limit risk, and brand safety. Be decisive — "
    "return safe=false if any category is a clear concern."
)

_POST_AUDIT_USER_TEMPLATE: Final[str] = (
    "--- BEGIN POST ---\n{content}\n--- END POST ---\n\n"
    "Return ONLY a JSON object with this exact shape:\n"
    "{{"
    '"safe": boolean, '
    '"confidence": number between 0 and 1, '
    '"reasons": [string, ...], '
    '"improved_version": string (may be empty)'
    "}}"
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class BridgeSafetyError(BridgeRuntimeError):
    """Raised when the safety layer itself fails (LLM error, bad JSON, etc.).

    This is distinct from a *safe=False* :class:`SafetyReport`: a failed
    ``SafetyReport`` still ran cleanly and produced a verdict. A
    ``BridgeSafetyError`` means the auditor could not form a verdict, and
    the caller should block the deploy by default.
    """


@dataclass(slots=True, frozen=True)
class SafetyReport:
    """Outcome of a single safety audit run.

    Attributes:
        safe: True iff no blocking issue was found.
        score: Confidence in the verdict, in [0, 1]. For
            :func:`scan_generated_code` this is ``1.0 - severity``;
            for :func:`audit_x_post` it mirrors the LLM's confidence.
        issues: Short, human-readable issue strings (static + LLM-reported).
        recommendations: Remediation hints to print alongside the report.
        estimated_cost_usd: Rough USD cost of the LLM audit (input + output),
            computed from the prompt length and ``max_tokens``. Separate
            from the actual cost billed by xAI — this is a planning number.
        estimated_tokens: Input + output token estimate used for ``estimated_cost_usd``.
        improved_version: Optional improved rewrite (X-post audit only).
    """

    safe: bool
    score: float
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    estimated_tokens: int = 0
    improved_version: str | None = None


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
#
# The token counts and rates below are deliberately pessimistic — we want
# operators to see a conservative upper bound in the report. The values
# track xAI's published grok-4.20-0309 pricing at the time of writing
# (USD per 1K tokens).

_USD_PER_1K_INPUT: Final[float] = 0.005
_USD_PER_1K_OUTPUT: Final[float] = 0.015
_CHARS_PER_TOKEN: Final[float] = 4.0

_MAX_POST_CHARS: Final[int] = 280
_DEFAULT_MAX_TOKENS: Final[int] = 8000


def _estimate(prompt: str, max_tokens: int) -> tuple[int, float]:
    """Return ``(estimated_tokens, estimated_cost_usd)`` for one audit call."""
    input_tokens = max(1, int(len(prompt) / _CHARS_PER_TOKEN))
    output_tokens = max_tokens  # worst-case assumption
    cost = (input_tokens / 1000.0) * _USD_PER_1K_INPUT + (
        output_tokens / 1000.0
    ) * _USD_PER_1K_OUTPUT
    return input_tokens + output_tokens, cost


def _max_tokens_from(config: dict[str, Any] | None) -> int:
    """Resolve ``config['safety']['max_tokens_per_run']`` or the default."""
    if not config:
        return _DEFAULT_MAX_TOKENS
    safety = config.get("safety") or {}
    value = safety.get("max_tokens_per_run", _DEFAULT_MAX_TOKENS)
    # Defensive: the parser already schema-validates this, but we may be
    # handed a plain dict from a test or a future API caller.
    if not isinstance(value, int) or value <= 0:
        return _DEFAULT_MAX_TOKENS
    return value


# ---------------------------------------------------------------------------
# Static scans
# ---------------------------------------------------------------------------


def _run_static_scans(code: str, language: str) -> list[str]:
    """Fast, offline regex sweep. Returns a list of issue strings.

    Right now the catalog is Python-centric; for other languages we still
    run the secret patterns (they are language-agnostic) but skip the
    runtime-construct patterns to avoid false positives. Extending the
    catalog per language goes in ``_patterns.py``.
    """
    secret_only = language.lower() not in {"python", "py"}
    issues: list[str] = []
    for pattern, message in STATIC_CHECKS:
        if secret_only and not message.startswith("hardcoded-secret"):
            continue
        if pattern.search(code):
            issues.append(message)
    return issues


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _call_llm_json(
    client: XAIClient,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Ask Grok for JSON, parse it, or raise :class:`BridgeSafetyError`.

    Args:
        client: An :class:`XAIClient`. Tests inject a fake here.
        system_prompt: Role + output-contract preamble.
        user_prompt: The artefact under review.
        max_tokens: Ceiling forwarded to the SDK.

    Returns:
        Parsed JSON as a dict.

    Raises:
        BridgeSafetyError: If the SDK call fails, the response is not
            parseable JSON, or the top-level JSON value is not an object.
    """
    try:
        raw = client.single_call(
            _AUDIT_MODEL,
            prompt=user_prompt,
            system=system_prompt,
            reasoning_effort="medium",
            max_tokens=max_tokens,
        )
    except BridgeRuntimeError as exc:
        raise BridgeSafetyError(
            f"safety audit LLM call failed: {exc}",
            suggestion=(
                "Re-run with --dry-run, inspect XAI_API_KEY/quota, or "
                "temporarily disable deploy.safety_scan."
            ),
        ) from exc

    # Grok sometimes wraps JSON in a ```json fence even when asked not to —
    # strip common fences before parsing so we don't fail on a benign pre/post.
    cleaned = _strip_json_fence(raw.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise BridgeSafetyError(
            f"safety auditor returned non-JSON: {cleaned[:200]!r}",
            suggestion="Retry — model output drift; if persistent, file a bug.",
        ) from exc

    if not isinstance(parsed, dict):
        raise BridgeSafetyError(
            f"safety auditor returned JSON of wrong shape (expected object): {type(parsed).__name__}",
        )
    return parsed


def _strip_json_fence(text: str) -> str:
    """Remove a trailing/leading ```json fence if present."""
    if text.startswith("```"):
        # Drop the opening fence line and the trailing ``` if any.
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_generated_code(
    code: str,
    language: str,
    *,
    config: dict[str, Any] | None = None,
    client: XAIClient | None = None,
) -> SafetyReport:
    """🛡️ Scan a generated codebase before it is allowed to deploy.

    Runs the regex-driven :data:`STATIC_CHECKS` and an LLM audit, then
    merges their findings.

    Args:
        code: Source code to audit (may be one file or a concatenation).
        language: One of ``python``, ``typescript``, ``go`` (or any string —
            unknown languages fall back to secrets-only static scanning).
        config: Optional bridge config dict. ``safety.max_tokens_per_run``
            caps the LLM audit's ``max_tokens``.
        client: Optional :class:`XAIClient`. Tests inject a mock here. If
            omitted, a fresh client is constructed — which means the caller
            must have ``XAI_API_KEY`` set.

    Returns:
        A :class:`SafetyReport`. ``safe`` is False if any issue was found.

    Raises:
        BridgeSafetyError: If the LLM audit fails.
    """
    section("🛡️  safety: scanning generated code")
    max_tokens = _max_tokens_from(config)

    static_issues = _run_static_scans(code, language)

    llm_client, llm_note = _resolve_client(client)
    if llm_client is None:
        # Degrade gracefully: return a static-only report with a breadcrumb
        # so the caller can see why the deep audit was skipped.
        return _static_only_code_report(static_issues, llm_note)

    user_prompt = _CODE_AUDIT_USER_TEMPLATE.format(language=language, code=code)
    parsed = _call_llm_json(
        llm_client,
        system_prompt=_CODE_AUDIT_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
    )

    llm_risks = [str(r) for r in parsed.get("risks", []) if r]
    llm_recommendations = [str(r) for r in parsed.get("recommendations", []) if r]
    severity = _coerce_unit_interval(parsed.get("severity", 0.0))

    all_issues = static_issues + llm_risks
    # Static issues are deterministic; seeing any one of them should push
    # the score down even if the LLM shrugged.
    static_weight = min(1.0, 0.3 * len(static_issues))
    score = max(0.0, min(1.0, 1.0 - max(severity, static_weight)))
    safe = not all_issues

    tokens, cost = _estimate(user_prompt, max_tokens)
    report = SafetyReport(
        safe=safe,
        score=score,
        issues=all_issues,
        recommendations=llm_recommendations,
        estimated_cost_usd=round(cost, 4),
        estimated_tokens=tokens,
    )

    if not safe:
        warn(f"⚠️  safety scan found {len(all_issues)} issue(s)")
    return report


def audit_x_post(
    content: str,
    config: dict[str, Any],
    *,
    client: XAIClient | None = None,
) -> SafetyReport:
    """🛡️ Audit a single X post (or thread) before publishing.

    Checks the per-post char limit, then asks Grok for a brand-safety read.

    Args:
        content: Post body. Threads may pass the concatenated text; the
            length check reports one issue per 280-char segment that would
            overflow.
        config: Bridge config dict (required). ``safety.max_tokens_per_run``
            caps the LLM audit's ``max_tokens``.
        client: Optional :class:`XAIClient` for testing.

    Returns:
        A :class:`SafetyReport` whose ``improved_version`` may carry a
        model-proposed rewrite when ``safe`` is False.

    Raises:
        BridgeSafetyError: If the LLM audit fails.
    """
    section("🛡️  safety: auditing X post")
    max_tokens = _max_tokens_from(config)

    issues: list[str] = []
    recommendations: list[str] = []

    # Length check. X's default free-tier post limit is 280 characters; paid
    # tiers get more, but we stay pessimistic so the generated agent works
    # for everyone.
    if len(content) > _MAX_POST_CHARS:
        overflow = len(content) - _MAX_POST_CHARS
        issues.append(
            f"post-too-long: {len(content)} chars exceeds {_MAX_POST_CHARS} "
            f"by {overflow} — split into a thread or shorten"
        )

    llm_client, llm_note = _resolve_client(client)
    if llm_client is None:
        # Without an auditor we cannot vouch for the post — block by default.
        issues.append(llm_note or "safety audit unavailable")
        return SafetyReport(
            safe=False,
            score=0.0,
            issues=issues,
            recommendations=["Set XAI_API_KEY to enable deep X-post audit."],
        )

    user_prompt = _POST_AUDIT_USER_TEMPLATE.format(content=content)
    parsed = _call_llm_json(
        llm_client,
        system_prompt=_POST_AUDIT_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
    )

    llm_safe = bool(parsed.get("safe", False))
    confidence = _coerce_unit_interval(parsed.get("confidence", 0.0))
    llm_reasons = [str(r) for r in parsed.get("reasons", []) if r]
    improved_version = parsed.get("improved_version") or None
    if improved_version is not None:
        improved_version = str(improved_version).strip() or None

    if not llm_safe:
        issues.extend(llm_reasons)
        if improved_version:
            recommendations.append(f"consider rewriting as: {improved_version!r}")

    safe = llm_safe and not issues
    tokens, cost = _estimate(user_prompt, max_tokens)

    report = SafetyReport(
        safe=safe,
        score=confidence,
        issues=issues,
        recommendations=recommendations,
        estimated_cost_usd=round(cost, 4),
        estimated_tokens=tokens,
        improved_version=improved_version if not safe else None,
    )
    if not safe:
        warn(f"⚠️  X-post audit flagged {len(issues)} issue(s)")
    return report


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _coerce_unit_interval(value: Any) -> float:
    """Clamp ``value`` to [0, 1]; coerce to float; fall back to 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _resolve_client(
    client: XAIClient | None,
) -> tuple[XAIClient | None, str | None]:
    """Return ``(client, note)``. ``note`` is set when we degraded gracefully.

    Passing ``client`` explicitly always wins. Otherwise we try to build one
    and absorb :class:`ConfigError` so the scan still produces a useful
    static-only report — missing an API key during ``--dry-run`` or in CI
    should not be fatal.
    """
    if client is not None:
        return client, None
    try:
        return XAIClient(), None
    except ConfigError as exc:
        warn(f"⚠️  skipping deep safety audit: {exc.message}")
        return None, (
            "llm-audit-skipped: no XAI_API_KEY available — static-only scan"
        )


def _static_only_code_report(
    static_issues: list[str], note: str | None
) -> SafetyReport:
    """Build a code-scan report when the LLM audit had to be skipped."""
    issues = list(static_issues)
    if note:
        issues.append(note)
    static_weight = min(1.0, 0.3 * len(static_issues))
    score = max(0.0, min(1.0, 1.0 - static_weight))
    return SafetyReport(
        safe=not static_issues,
        score=score,
        issues=issues,
        recommendations=[
            "Set XAI_API_KEY to enable the LLM half of the safety audit.",
        ],
    )
