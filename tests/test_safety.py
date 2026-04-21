"""Tests for :mod:`grok_build_bridge.safety`.

Every test uses a ``_FakeClient`` in place of the real :class:`XAIClient`
so no network traffic is ever generated. The fake records every call and
returns canned JSON strings from a script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from grok_build_bridge.safety import (
    BridgeSafetyError,
    SafetyReport,
    audit_x_post,
    scan_generated_code,
)

# ---------------------------------------------------------------------------
# Fake XAIClient
# ---------------------------------------------------------------------------


@dataclass
class _FakeClient:
    """Stand-in for :class:`grok_build_bridge.xai_client.XAIClient`.

    ``responses`` is consumed FIFO on each ``single_call``. Each item may
    be a string (returned verbatim), a callable (called with kwargs and
    returning a string), or an ``Exception`` (raised).
    """

    responses: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def single_call(self, model: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"model": model, "prompt": prompt, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("FakeClient has no more scripted responses")
        head = self.responses.pop(0)
        if isinstance(head, Exception):
            raise head
        if callable(head):
            return head(model=model, prompt=prompt, **kwargs)
        return str(head)


def _code_audit_json(
    risks: list[str] | None = None,
    severity: float = 0.0,
    recommendations: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "risks": risks or [],
            "severity": severity,
            "recommendations": recommendations or [],
        }
    )


def _post_audit_json(
    safe: bool,
    confidence: float,
    reasons: list[str] | None = None,
    improved_version: str = "",
) -> str:
    return json.dumps(
        {
            "safe": safe,
            "confidence": confidence,
            "reasons": reasons or [],
            "improved_version": improved_version,
        }
    )


# ---------------------------------------------------------------------------
# SafetyReport semantics
# ---------------------------------------------------------------------------


def test_safety_report_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    report = SafetyReport(safe=True, score=1.0)
    with pytest.raises(FrozenInstanceError):
        report.safe = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# scan_generated_code
# ---------------------------------------------------------------------------


CLEAN_PYTHON: str = """
import time


def main() -> None:
    print('hello world')
    time.sleep(1)
"""

CODE_WITH_XAI_KEY: str = """
API_KEY = 'xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef0123456789'
print(API_KEY)
"""

CODE_WITH_SHELL_TRUE: str = """
import subprocess
subprocess.run('ls -la', shell=True)
"""

CODE_WITH_OS_SYSTEM: str = 'import os; os.system("rm -rf /")'

CODE_WITH_EVAL: str = "x = eval(input('enter: '))"

CODE_WITH_NO_TIMEOUT: str = "import requests; r = requests.get('https://x.ai/health')"


@pytest.mark.parametrize(
    ("code", "slug_expected"),
    [
        pytest.param(CODE_WITH_XAI_KEY, "hardcoded-secret", id="xai-key-flagged"),
        pytest.param(CODE_WITH_SHELL_TRUE, "shell-call", id="shell-true-flagged"),
        pytest.param(CODE_WITH_OS_SYSTEM, "shell-call", id="os-system-flagged"),
        pytest.param(CODE_WITH_EVAL, "unsafe-eval", id="eval-flagged"),
        pytest.param(CODE_WITH_NO_TIMEOUT, "no-timeout", id="no-timeout-flagged"),
    ],
)
def test_static_issues_flagged(code: str, slug_expected: str) -> None:
    client = _FakeClient(responses=[_code_audit_json()])
    report = scan_generated_code(code, "python", client=client)
    assert report.safe is False
    assert any(i.startswith(slug_expected) for i in report.issues), report.issues


def test_clean_code_passes_when_llm_agrees() -> None:
    client = _FakeClient(responses=[_code_audit_json()])
    report = scan_generated_code(CLEAN_PYTHON, "python", client=client)
    assert report.safe is True
    assert report.issues == []
    assert 0.0 <= report.score <= 1.0
    assert report.score == pytest.approx(1.0)


def test_llm_risks_are_merged_into_issues() -> None:
    client = _FakeClient(
        responses=[
            _code_audit_json(
                risks=["may post faster than X rate limits allow"],
                severity=0.5,
                recommendations=["add a token bucket before .post"],
            )
        ]
    )
    report = scan_generated_code(CLEAN_PYTHON, "python", client=client)
    assert report.safe is False
    assert "may post faster than X rate limits allow" in report.issues
    assert "add a token bucket before .post" in report.recommendations
    assert report.score == pytest.approx(0.5)


def test_config_respects_max_tokens_per_run() -> None:
    client = _FakeClient(responses=[_code_audit_json()])
    config = {"safety": {"max_tokens_per_run": 1234}}
    scan_generated_code(CLEAN_PYTHON, "python", config=config, client=client)
    # Verify the forwarded max_tokens matches config.
    assert client.calls[0]["kwargs"]["max_tokens"] == 1234


def test_cost_estimate_is_populated() -> None:
    client = _FakeClient(responses=[_code_audit_json()])
    report = scan_generated_code(CLEAN_PYTHON, "python", client=client)
    assert report.estimated_tokens > 0
    assert report.estimated_cost_usd > 0


def test_llm_json_parse_error_raises_bridge_safety_error() -> None:
    client = _FakeClient(responses=["not json at all"])
    with pytest.raises(BridgeSafetyError, match="non-JSON"):
        scan_generated_code(CLEAN_PYTHON, "python", client=client)


def test_llm_returns_json_array_raises_bridge_safety_error() -> None:
    # Top-level must be an object, not a list.
    client = _FakeClient(responses=["[1, 2, 3]"])
    with pytest.raises(BridgeSafetyError, match="wrong shape"):
        scan_generated_code(CLEAN_PYTHON, "python", client=client)


def test_llm_call_failure_escalates_as_bridge_safety_error() -> None:
    from grok_build_bridge.xai_client import BridgeRuntimeError

    client = _FakeClient(responses=[BridgeRuntimeError("rate limit")])
    with pytest.raises(BridgeSafetyError, match="LLM call failed"):
        scan_generated_code(CLEAN_PYTHON, "python", client=client)


def test_non_python_language_skips_runtime_patterns() -> None:
    # The eval() pattern would fire for Python; for TypeScript we only run
    # secret checks. Use code that would trigger eval() in Python only.
    client = _FakeClient(responses=[_code_audit_json()])
    ts_code = "const x = eval(userInput);"
    report = scan_generated_code(ts_code, "typescript", client=client)
    # Secret-only scans pass this code through without flagging eval().
    assert all(not i.startswith("unsafe-eval") for i in report.issues)


def test_json_fenced_response_is_still_parsed() -> None:
    fenced = "```json\n" + _code_audit_json() + "\n```"
    client = _FakeClient(responses=[fenced])
    report = scan_generated_code(CLEAN_PYTHON, "python", client=client)
    assert report.safe is True


# ---------------------------------------------------------------------------
# audit_x_post
# ---------------------------------------------------------------------------


def test_clean_x_post_passes() -> None:
    client = _FakeClient(responses=[_post_audit_json(safe=True, confidence=0.95)])
    report = audit_x_post("Just shipped v0.1 of the bridge.", {}, client=client)
    assert report.safe is True
    assert report.score == pytest.approx(0.95)
    assert report.issues == []
    assert report.improved_version is None


def test_toxic_x_post_flagged() -> None:
    client = _FakeClient(
        responses=[
            _post_audit_json(
                safe=False,
                confidence=0.9,
                reasons=["toxic phrasing about group X"],
                improved_version="A rewrite without the slur.",
            )
        ]
    )
    report = audit_x_post("some really nasty content", {}, client=client)
    assert report.safe is False
    assert "toxic phrasing about group X" in report.issues
    assert report.improved_version == "A rewrite without the slur."
    assert any("rewriting" in r for r in report.recommendations)


def test_post_too_long_flagged_even_if_llm_says_safe() -> None:
    long_content = "a" * 400
    client = _FakeClient(responses=[_post_audit_json(safe=True, confidence=0.99)])
    report = audit_x_post(long_content, {}, client=client)
    assert report.safe is False
    assert any(i.startswith("post-too-long") for i in report.issues)


def test_audit_x_post_respects_max_tokens_per_run() -> None:
    client = _FakeClient(responses=[_post_audit_json(safe=True, confidence=0.9)])
    config = {"safety": {"max_tokens_per_run": 4321}}
    audit_x_post("short", config, client=client)
    assert client.calls[0]["kwargs"]["max_tokens"] == 4321


def test_audit_x_post_llm_failure_escalates() -> None:
    from grok_build_bridge.xai_client import BridgeRuntimeError

    client = _FakeClient(responses=[BridgeRuntimeError("boom")])
    with pytest.raises(BridgeSafetyError):
        audit_x_post("hello", {}, client=client)


# ---------------------------------------------------------------------------
# Graceful degradation when no API key is available
# ---------------------------------------------------------------------------


def test_scan_without_client_and_no_key_returns_static_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    report = scan_generated_code(CODE_WITH_OS_SYSTEM, "python")
    assert report.safe is False
    assert any(i.startswith("shell-call") for i in report.issues)
    assert any(i.startswith("llm-audit-skipped") for i in report.issues)


def test_audit_post_without_client_and_no_key_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    # No LLM → can't vouch for the post → block.
    report = audit_x_post("hello", {})
    assert report.safe is False
    assert report.score == 0.0
