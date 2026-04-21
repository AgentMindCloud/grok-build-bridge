"""Shared pytest fixtures and session hooks for the grok-build-bridge tests.

Everything here is consumed via ``pytest``'s fixture lookup so individual
test modules can stay focused on what they actually exercise. Heavy fixtures
(mock xAI client, isolated bridge workspace) live here because they are
needed in more than one module and keeping them in sync across copies is
the kind of drift that silently erodes a test suite.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

_NO_TESTS_COLLECTED: int = 5


# ---------------------------------------------------------------------------
# Session hook
# ---------------------------------------------------------------------------


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Treat "no tests collected" as success — keeps early scaffolds green."""
    if exitstatus == _NO_TESTS_COLLECTED:
        session.exitstatus = 0


# ---------------------------------------------------------------------------
# Fake xAI client
# ---------------------------------------------------------------------------


@dataclass
class MockXAIClient:
    """In-process stand-in for :class:`grok_build_bridge.xai_client.XAIClient`.

    ``stream_chat`` emits a single response carrying a canned fenced code
    block; ``single_call`` replies with canned JSON sufficient for the
    safety-audit path. Both record their calls on ``self.calls`` so tests
    can assert on the model / kwargs used.
    """

    code_block: str = '```python\n"""generated."""\n\n\ndef main() -> None:\n    print("ok")\n```'
    audit_json: str = field(
        default_factory=lambda: json.dumps({"risks": [], "severity": 0.0, "recommendations": []})
    )
    post_audit_json: str = field(
        default_factory=lambda: json.dumps(
            {
                "safe": True,
                "confidence": 0.95,
                "reasons": [],
                "improved_version": "",
            }
        )
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    # -- Streaming -----------------------------------------------------------

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str = "medium",
        include_verbose_streaming: bool = False,
        use_encrypted_content: bool = False,
        max_tokens: int = 8000,
    ) -> Iterator[tuple[Any, Any]]:
        self.calls.append(
            {
                "method": "stream_chat",
                "model": model,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
            }
        )

        class _Resp:
            content = self.code_block

        yield _Resp(), "chunk"

    # -- Non-streaming -------------------------------------------------------

    def single_call(self, model: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"method": "single_call", "model": model, "prompt": prompt, **kwargs})
        # Route based on the prompt body so one mock can serve both the code
        # audit and the X-post audit without a second configuration knob.
        if "BEGIN POST" in prompt:
            return self.post_audit_json
        return self.audit_json


@pytest.fixture
def mock_xai_client() -> MockXAIClient:
    """Default fake client — returns clean code + clean safety verdict."""
    return MockXAIClient()


# ---------------------------------------------------------------------------
# Bridge workspace
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeWorkspace:
    """One temporary project dir with the common on-disk shape of a bridge run.

    Attributes:
        root: The isolated tmp path (also becomes the cwd during the test).
        yaml_path: Path where :meth:`write_bridge` will write its YAML.
    """

    root: Path
    yaml_path: Path

    def write_bridge(self, yaml_text: str) -> Path:
        self.yaml_path.write_text(yaml_text, encoding="utf-8")
        return self.yaml_path

    def write_entrypoint(self, relpath: str, content: str) -> Path:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


@pytest.fixture
def tmp_bridge_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BridgeWorkspace:
    """Per-test isolated bridge workspace with cwd = tmp_path and no XAI_API_KEY."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    return BridgeWorkspace(root=tmp_path, yaml_path=tmp_path / "bridge.yaml")


# ---------------------------------------------------------------------------
# YAML fixture strings
# ---------------------------------------------------------------------------


BRIDGE_MINIMAL_YAML: str = """\
version: "1.0"
name: minimal-test-bot
description: Minimal bridge used by shared test fixtures.
build:
  source: local
  language: python
  entrypoint: main.py
deploy:
  target: local
agent:
  model: grok-4.20-0309
safety:
  audit_before_post: false
"""

BRIDGE_GROK_YAML: str = """\
version: "1.0"
name: grok-test-bot
description: Grok-sourced bridge used by shared test fixtures.
build:
  source: grok
  grok_prompt: Build a Python script that prints "hi".
  language: python
  entrypoint: main.py
deploy:
  target: local
agent:
  model: grok-4.20-0309
safety:
  audit_before_post: false
"""

HELLO_MAIN_PY: str = '''\
"""Generated hello script."""

from __future__ import annotations


def main() -> None:
    print("hello!")


if __name__ == "__main__":
    main()
'''


@pytest.fixture
def minimal_bridge_yaml() -> str:
    return BRIDGE_MINIMAL_YAML


@pytest.fixture
def grok_bridge_yaml() -> str:
    return BRIDGE_GROK_YAML


@pytest.fixture
def hello_main_py() -> str:
    return HELLO_MAIN_PY
