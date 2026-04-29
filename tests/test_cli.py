"""Tests for :mod:`grok_build_bridge.cli` driven through Typer's :class:`CliRunner`.

The CLI is exercised with the real Typer app but injected into a captured
stdout/stderr environment. ``XAI_API_KEY`` is stripped so no real network
calls are attempted; the ``run`` command degrades to the static-only
safety scan path that Session 4 already covers.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from grok_build_bridge.cli import app

runner = CliRunner()

# Typer's Rich-rendered help wraps option names like ``--dry-run`` in ANSI
# colour spans whose splits depend on terminal width and Rich version
# (locally one span, on GitHub's runners two: ``-`` then ``-dry-run``).
# Strip the ANSI in the test helper so substring checks are colour-agnostic.
_ANSI_RE: re.Pattern[str] = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _combined_output(result: Any) -> str:
    """Return stdout + stderr together with ANSI escape codes stripped.

    Newer click splits the two streams, our Rich console writes to stderr,
    and Typer's Rich help inserts colour codes mid-token — flatten all of
    that into a plain string so tests can do simple substring assertions.
    """
    parts = [getattr(result, "output", "") or ""]
    try:
        parts.append(result.stderr or "")
    except (AttributeError, ValueError):
        pass
    return _ANSI_RE.sub("", "".join(parts))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


_HELLO_MAIN = '''\
"""Hello bot."""
from __future__ import annotations


def main() -> None:
    print("hi")


if __name__ == "__main__":
    main()
'''


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each test in an isolated cwd and strip the xAI key."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _write_valid_yaml(tmp_path: Path, name: str = "cli-bot") -> Path:
    (tmp_path / name).mkdir()
    (tmp_path / name / "main.py").write_text(_HELLO_MAIN, encoding="utf-8")
    yaml_path = tmp_path / "bridge.yaml"
    yaml_path.write_text(
        f"""\
version: "1.0"
name: {name}
description: CLI-test bot.
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


# ---------------------------------------------------------------------------
# version + help
# ---------------------------------------------------------------------------


def test_version_command_prints_three_versions() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, _combined_output(result)
    out = _combined_output(result)
    assert "grok-build-bridge" in out
    assert "xai-sdk" in out
    assert "python" in out


def test_global_version_flag_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_run_help_shows_branded_help() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    out = _combined_output(result)
    assert "grok-build-bridge" in out.lower() or "build" in out.lower()
    assert "--dry-run" in out
    assert "--force" in out
    # ``--allow-stub`` lets the user opt into the historical fallback paths
    # (deploy.py:_dry_run_stub and the grok-build-cli substitute) — present
    # in the help output so users know how to recover when deps are absent.
    assert "--allow-stub" in out


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_valid_yaml(tmp_path: Path) -> None:
    yaml_path = _write_valid_yaml(tmp_path)
    result = runner.invoke(app, ["validate", str(yaml_path)])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    assert "valid" in out.lower() or "✅" in out


def test_validate_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 'bogus'\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(bad)])
    # Invalid schema → exit code 2 (config).
    assert result.exit_code == 2
    assert "Config Error" in _combined_output(result)


def test_validate_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# run --dry-run
# ---------------------------------------------------------------------------


def test_run_dry_run_exits_zero(tmp_path: Path) -> None:
    yaml_path = _write_valid_yaml(tmp_path)
    result = runner.invoke(app, ["run", str(yaml_path), "--dry-run"])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    # Each phase header and the final success panel should all be in stderr.
    assert "phase 1" in out
    assert "phase 5" in out
    assert "Bridge complete" in out


def test_run_on_nonexistent_file_exits_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(tmp_path / "absent.yaml"), "--dry-run"])
    # Typer's own validation for readable file paths returns exit code 2
    # before our handlers run; our Config Error path returns 2 as well.
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# templates + init
# ---------------------------------------------------------------------------


def test_templates_command_lists_bundled_hello_bot() -> None:
    result = runner.invoke(app, ["templates"])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    assert "hello-bot" in out


def test_templates_command_lists_all_six_bundled_templates() -> None:
    """Every INDEX.yaml slug should appear in the templates table."""
    result = runner.invoke(app, ["templates"])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    for slug in [
        "hello-bot",
        "x-trend-analyzer",
        "truthseeker-daily",
        "code-explainer-bot",
        "grok-build-coding-agent",
        "research-thread-weekly",
    ]:
        assert slug in out, f"expected template {slug} in output, got: {out}"


def test_init_for_flat_template_copies_to_bridge_yaml(tmp_path: Path) -> None:
    """Flat-style templates (INDEX `files: [{src, dst: bridge.yaml}]`) land as bridge.yaml."""
    out = tmp_path / "flat-template-out"
    result = runner.invoke(app, ["init", "x-trend-analyzer", "--out", str(out), "--force"])
    assert result.exit_code == 0, _combined_output(result)
    assert (out / "bridge.yaml").is_file()
    # The copied file should be the x-trend-analyzer YAML.
    copied = (out / "bridge.yaml").read_text(encoding="utf-8")
    assert "x-trend-analyzer" in copied
    assert "x_search" in copied


def test_init_copies_bundled_template_into_out_dir(tmp_path: Path) -> None:
    out = tmp_path / "new-project"
    result = runner.invoke(app, ["init", "hello-bot", "--out", str(out), "--force"])
    assert result.exit_code == 0, _combined_output(result)
    assert (out / "bridge.yaml").is_file()
    assert (out / "hello-bot" / "main.py").is_file()


def test_init_unknown_template_exits_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "does-not-exist", "--out", str(tmp_path / "x")])
    assert result.exit_code == 2


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / "existing"
    out.mkdir()
    pre_existing = out / "bridge.yaml"
    pre_existing.write_text("original: content\n", encoding="utf-8")

    # Respond "n" (no) to the overwrite prompt.
    result = runner.invoke(app, ["init", "hello-bot", "--out", str(out)], input="n\n")
    assert result.exit_code == 0
    assert pre_existing.read_text() == "original: content\n"


# ---------------------------------------------------------------------------
# Exit-code contract
# ---------------------------------------------------------------------------


def test_config_error_exit_code(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not: a: mapping\n", encoding="utf-8")
    result = runner.invoke(app, ["run", str(bad), "--dry-run"])
    # Parse phase config error → exit 2
    assert result.exit_code == 2


def test_safety_error_exit_code(tmp_path: Path) -> None:
    yaml_path = _write_valid_yaml(tmp_path)
    # Overwrite the entrypoint with code that fails the static scan.
    (tmp_path / "cli-bot" / "main.py").write_text(
        'import os\nos.system("echo nope")\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["run", str(yaml_path), "--dry-run"])
    # Safety scan blocks → exit 4
    out = _combined_output(result)
    assert result.exit_code == 4, out
    assert "Safety Error" in out


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_passes_with_xai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "sk-test")
    result = runner.invoke(app, ["doctor"])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    # The required-surface rows must all be present.
    assert "python" in out
    assert "xai-sdk" in out
    assert "XAI_API_KEY" in out
    assert "all required checks pass" in out


def test_doctor_fails_without_xai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    result = runner.invoke(app, ["doctor"])
    out = _combined_output(result)
    # Required check failed → exit 3 (runtime).
    assert result.exit_code == 3, out
    assert "XAI_API_KEY" in out
    assert "doctor failed" in out


def test_doctor_warns_on_optional_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing optional deploy CLIs should be warnings, not failures."""
    monkeypatch.setenv("XAI_API_KEY", "sk-test")
    # Force PATH to a single empty dir so no CLIs are findable.
    empty_dir = Path("/tmp") / "doctor-empty-path"
    empty_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_dir))
    result = runner.invoke(app, ["doctor"])
    out = _combined_output(result)
    assert result.exit_code == 0, out
    # Each optional CLI row should show the warn glyph somewhere in the table.
    for cli in ("vercel", "railway", "flyctl", "grok-build"):
        assert cli in out
