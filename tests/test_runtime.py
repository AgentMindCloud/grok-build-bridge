"""End-to-end tests for :mod:`grok_build_bridge.runtime`.

Every test drives :func:`run_bridge` with a temp YAML + a mock
:class:`XAIClient` so nothing in these tests touches the real xAI API.
We rely on the ``local`` build source to avoid needing a live model for
code generation; the safety phase's LLM call is served by the fake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from grok_build_bridge.runtime import (
    BridgePhaseError,
    BridgeResult,
    run_bridge,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeClient:
    """Fake XAIClient — returns canned JSON for the safety-scan call."""

    responses: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def single_call(self, model: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"model": model, "prompt": prompt, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        head = self.responses.pop(0)
        if isinstance(head, Exception):
            raise head
        return str(head)

    # stream_chat is called by builder.generate_code for the ``grok`` source;
    # our local-source fixtures never reach it, but include a stub so any
    # future test that switches to source=grok has a sensible default.
    def stream_chat(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("stream_chat should not be called for source=local")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_HELLO_CODE = '''\
"""Hello bot."""
from __future__ import annotations


def main() -> None:
    print("hello!")


if __name__ == "__main__":
    main()
'''


def _write_project(tmp_path: Path, name: str = "e2e-bridge") -> Path:
    """Lay out a temp bridge project and return the path to its YAML file."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / name).mkdir()
    (proj / name / "main.py").write_text(_HELLO_CODE, encoding="utf-8")

    yaml_path = proj / "bridge.yaml"
    yaml_path.write_text(
        f"""\
version: "1.0"
name: {name}
description: End-to-end runtime test bot.
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
""",
        encoding="utf-8",
    )
    return yaml_path


@pytest.fixture
def cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test in an isolated cwd so generated/ never escapes tmp."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_client() -> _FakeClient:
    return _FakeClient(
        responses=[json.dumps({"risks": [], "severity": 0.0, "recommendations": []})]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_executes_all_five_phases(
    cwd: Path,
    fake_client: _FakeClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    yaml_path = _write_project(cwd)

    result = run_bridge(yaml_path, dry_run=True, client=fake_client)

    # Verdict shape.
    assert isinstance(result, BridgeResult)
    assert result.success is True
    assert result.deploy_target == "local"
    # Dry run skips phase 4, so deploy_url is unset.
    assert result.deploy_url is None
    assert result.safety_report is not None
    assert result.safety_report.safe is True
    assert result.generated_path is not None
    assert (result.generated_path / "main.py").is_file()
    assert (result.generated_path / "bridge.manifest.json").is_file()

    # Exactly one LLM call fired — the safety scan (builder uses source=local).
    assert len(fake_client.calls) == 1

    # All five phase headers printed, in order.
    err = capsys.readouterr().err
    # Rich renders the rule text with ──── separators — check the emoji slug
    # for each phase instead to keep the match robust to width tweaks.
    for slug in [
        "phase 1",
        "phase 2",
        "phase 3",
        "phase 4",
        "phase 5",
    ]:
        assert slug in err, f"expected {slug!r} in output, got: {err}"


def test_deploy_url_is_populated_when_not_dry_run(
    cwd: Path,
    fake_client: _FakeClient,
) -> None:
    yaml_path = _write_project(cwd)

    result = run_bridge(yaml_path, dry_run=False, client=fake_client)

    assert result.success is True
    # For target=local, the deploy_url is the generated directory path.
    assert result.deploy_url is not None
    assert str(result.generated_path) in result.deploy_url


def test_safety_failure_aborts_deploy_without_force(
    cwd: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    yaml_path = _write_project(cwd)
    # Rewrite the entrypoint to something the static scan will reject.
    (yaml_path.parent / "e2e-bridge" / "main.py").write_text(
        'import os\nos.system("rm -rf /tmp/nope")\n', encoding="utf-8"
    )

    # LLM agrees (severity 0) but static catches os.system — should block.
    client = _FakeClient(responses=[json.dumps({"risks": [], "severity": 0.0})])
    with pytest.raises(BridgePhaseError) as excinfo:
        run_bridge(yaml_path, dry_run=True, client=client)
    assert excinfo.value.phase == "safety"


def test_force_flag_bypasses_safety_block(
    cwd: Path,
) -> None:
    yaml_path = _write_project(cwd)
    (yaml_path.parent / "e2e-bridge" / "main.py").write_text(
        'import os\nos.system("echo bad")\n', encoding="utf-8"
    )
    client = _FakeClient(responses=[json.dumps({"risks": [], "severity": 0.0})])

    result = run_bridge(yaml_path, dry_run=True, force=True, client=client)
    assert result.success is True
    assert result.safety_report is not None
    assert result.safety_report.safe is False


def test_phase_errors_are_tagged(cwd: Path, fake_client: _FakeClient) -> None:
    yaml_path = cwd / "bridge.yaml"
    yaml_path.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(BridgePhaseError) as excinfo:
        run_bridge(yaml_path, dry_run=True, client=fake_client)
    assert excinfo.value.phase == "parse"


def test_manifest_contains_expected_fields(
    cwd: Path,
    fake_client: _FakeClient,
) -> None:
    yaml_path = _write_project(cwd)
    result = run_bridge(yaml_path, dry_run=True, client=fake_client)
    assert result.generated_path is not None
    manifest = json.loads((result.generated_path / "bridge.manifest.json").read_text())
    assert manifest["name"] == "e2e-bridge"
    assert manifest["source"] == "local"
    assert manifest["entrypoint"] == "main.py"
    assert "generated_at" in manifest
    assert manifest["model"] == "grok-4.20-0309"
    assert "main.py" in manifest["files"]
