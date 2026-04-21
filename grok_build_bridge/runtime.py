"""End-to-end bridge orchestrator.

Walks the five phases that turn a YAML into a deployed X agent:

1. 📄  Parse & validate YAML
2. 🎯  Generate code (via :func:`grok_build_bridge.builder.generate_code`)
3. 🛡️  Safety scan (via :func:`grok_build_bridge.safety.scan_generated_code`)
4. 🚀  Deploy (via :func:`grok_build_bridge.deploy.deploy_to_target`)
5. ✅  Emit :class:`BridgeResult`

Every exception is tagged with the phase it occurred in so the CLI and
future UIs can render it with accurate context.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from grok_build_bridge._console import (
    console,
    error,
    info,
    phase_progress,
    section,
    warn,
)
from grok_build_bridge.builder import generate_code
from grok_build_bridge.deploy import deploy_to_target
from grok_build_bridge.parser import BridgeConfigError, load_yaml
from grok_build_bridge.safety import (
    BridgeSafetyError,
    SafetyReport,
    scan_generated_code,
)
from grok_build_bridge.xai_client import (
    BridgeRuntimeError,
    ConfigError,
    XAIClient,
)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BridgeResult:
    """Summary of one ``run_bridge`` invocation.

    ``success`` is False iff any phase raised — the exception propagates to
    the caller either way, and this field captures the verdict for display
    purposes when the caller wants to render the result without re-raising.
    """

    success: bool
    generated_path: Path | None
    safety_report: SafetyReport | None
    deploy_target: str | None
    deploy_url: str | None
    duration_seconds: float
    total_tokens: int


class BridgePhaseError(BridgeRuntimeError):
    """Wraps an exception with the phase it occurred in for cleaner reporting."""

    def __init__(self, phase: str, cause: BaseException) -> None:
        message = f"[{phase}] {cause}"
        suggestion = getattr(cause, "suggestion", None)
        super().__init__(message, suggestion=suggestion)
        self.phase: str = phase
        self.cause: BaseException = cause


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _thaw(value: Any) -> Any:
    """Recursively convert ``MappingProxyType``/tuples back to dict/list.

    :func:`grok_build_bridge.parser.load_yaml` returns a frozen structure,
    but downstream modules expect plain dicts (they mutate sub-dicts in
    builder/deploy, and they pass the config through the xAI JSON pipeline).
    Unfreezing once at the orchestrator boundary keeps every other module
    free of the ``MappingProxyType`` type and its surprises.
    """
    from types import MappingProxyType

    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _safe_build_client(explicit: XAIClient | None) -> XAIClient | None:
    """Return a usable client; gracefully degrade when no API key is set."""
    if explicit is not None:
        return explicit
    try:
        return XAIClient()
    except ConfigError as exc:
        warn(f"⚠️  XAI_API_KEY not set — some phases will degrade ({exc.message})")
        return None


def _print_result_panel(result: BridgeResult) -> None:
    """Render the final :class:`BridgeResult` as a green success panel."""
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("field", style="brand.primary", no_wrap=True)
    table.add_column("value")
    table.add_row("success", "yes" if result.success else "no")
    table.add_row("generated_path", str(result.generated_path or ""))
    if result.safety_report is not None:
        table.add_row(
            "safety",
            f"safe={result.safety_report.safe}  "
            f"score={result.safety_report.score:.2f}  "
            f"issues={len(result.safety_report.issues)}",
        )
    table.add_row("deploy_target", result.deploy_target or "")
    table.add_row("deploy_url", result.deploy_url or "")
    table.add_row("duration", f"{result.duration_seconds:.2f}s")
    table.add_row("tokens (est.)", str(result.total_tokens))

    title_style = "brand.success" if result.success else "brand.error"
    title_text = "✅ Bridge complete" if result.success else "🚫 Bridge failed"
    border = "brand.success" if result.success else "brand.error"
    console.print(
        Panel(
            table,
            title=f"[{title_style}]{title_text}[/]",
            border_style=border,
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_bridge(
    yaml_path: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    client: XAIClient | None = None,
) -> BridgeResult:
    """Drive a YAML config through all five bridge phases.

    Args:
        yaml_path: Path to the bridge YAML.
        dry_run: When True, phases 1-3 run normally but phase 4 is skipped.
        force: When True, a failing safety report does not abort phase 4.
        client: Optional injected :class:`XAIClient` — tests pass a fake.

    Returns:
        A :class:`BridgeResult` summarising every phase.

    Raises:
        BridgePhaseError: Wraps any per-phase failure with phase context.
    """
    yaml_path = Path(yaml_path)
    started = time.monotonic()

    generated_path: Path | None = None
    safety_report: SafetyReport | None = None
    deploy_url: str | None = None
    deploy_target: str | None = None
    total_tokens = 0

    # --- Phase 1 ---------------------------------------------------------
    section("📄  phase 1 — parse & validate YAML")
    try:
        frozen_cfg = load_yaml(yaml_path)
    except BridgeConfigError as exc:
        raise BridgePhaseError("parse", exc) from exc
    config: dict[str, Any] = _thaw(frozen_cfg)
    info(f"config ok: name={config['name']!r}, source={config['build']['source']!r}")

    # Resolve the xAI client once for phases 2 and 3. Phase 4's X-audit
    # reuses the same client.
    resolved_client = _safe_build_client(client)

    # --- Phase 2 ---------------------------------------------------------
    section("🎯  phase 2 — generate code")
    with phase_progress("🎯  generating") as (prog, task):
        try:
            generated_path = generate_code(
                config,
                resolved_client,
                yaml_dir=yaml_path.parent,
            )
        except BridgeRuntimeError as exc:
            raise BridgePhaseError("build", exc) from exc
        prog.update(task, tokens=0)
    info(f"generated: {generated_path}")

    # --- Phase 3 ---------------------------------------------------------
    section("🛡️  phase 3 — safety scan")
    with phase_progress("🛡️  scanning") as (prog, task):
        try:
            entrypoint = config["build"]["entrypoint"]
            code_text = (generated_path / entrypoint).read_text(encoding="utf-8")
            safety_report = scan_generated_code(
                code_text,
                language=config["build"]["language"],
                config=config,
                client=resolved_client,
            )
        except BridgeRuntimeError as exc:
            raise BridgePhaseError("safety", exc) from exc
        prog.update(task, tokens=safety_report.estimated_tokens)
    total_tokens += safety_report.estimated_tokens

    if not safety_report.safe:
        for issue in safety_report.issues:
            warn(f"• {issue}")
        if not force:
            result = BridgeResult(
                success=False,
                generated_path=generated_path,
                safety_report=safety_report,
                deploy_target=config["deploy"]["target"],
                deploy_url=None,
                duration_seconds=time.monotonic() - started,
                total_tokens=total_tokens,
            )
            _print_result_panel(result)
            raise BridgePhaseError(
                "safety",
                BridgeSafetyError(
                    f"safety scan blocked the deploy ({len(safety_report.issues)} issue(s))",
                    suggestion=(
                        "Fix the reported issues, or re-run with --force to deploy anyway."
                    ),
                ),
            )
        warn("--force given — proceeding despite safety findings")

    # --- Phase 4 ---------------------------------------------------------
    section("🚀  phase 4 — deploy")
    deploy_target = config["deploy"]["target"]
    if dry_run:
        info(f"dry-run: skipping deploy to {deploy_target!r}")
    else:
        with phase_progress("🚀  deploying") as (prog, task):
            try:
                deploy_url = deploy_to_target(generated_path, config, client=resolved_client)
            except BridgeRuntimeError as exc:
                raise BridgePhaseError("deploy", exc) from exc
            prog.update(task, tokens=0)

    # --- Phase 5 ---------------------------------------------------------
    section("✅  phase 5 — summary")
    duration = time.monotonic() - started
    result = BridgeResult(
        success=True,
        generated_path=generated_path,
        safety_report=safety_report,
        deploy_target=deploy_target,
        deploy_url=deploy_url,
        duration_seconds=duration,
        total_tokens=total_tokens,
    )
    _print_result_panel(result)
    return result


# ---------------------------------------------------------------------------
# Back-compat alias
# ---------------------------------------------------------------------------


async def bridge(
    config_path: str | Path,
    *,
    dry_run: bool = False,
) -> BridgeResult:
    """🚀 Async façade that forwards to :func:`run_bridge`.

    Kept for compatibility with the session-1 scaffolding that declared an
    async entrypoint. The current implementation is synchronous, so the
    coroutine just awaits a trivial sync call.
    """
    return run_bridge(config_path, dry_run=dry_run)


def _report_error(exc: BaseException) -> None:
    """Print a phase-tagged failure to the shared console (used by the CLI)."""
    if isinstance(exc, BridgePhaseError):
        error(f"bridge failed in phase {exc.phase!r}: {exc.cause}")
    else:
        error(f"bridge failed: {exc}")
