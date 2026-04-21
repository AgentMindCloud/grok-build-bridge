"""End-to-end dry-run over every bundled template.

For each template listed in ``INDEX.yaml``, copy it into a temp workspace,
fabricate whatever ancillary files its build source needs (a pre-existing
entrypoint for ``local``, a mocked XAIClient for ``grok`` /
``grok-build-cli``), and drive :func:`run_bridge` with ``dry_run=True``.

No real network traffic is ever generated — ``MockXAIClient`` from
``conftest.py`` services both the streaming build and the safety-scan LLM
call.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from grok_build_bridge.runtime import BridgeResult, run_bridge
from tests.conftest import HELLO_MAIN_PY, BridgeWorkspace, MockXAIClient

_TEMPLATES_ROOT = Path(__file__).parent.parent / "grok_build_bridge" / "templates"
_INDEX_PATH = _TEMPLATES_ROOT / "INDEX.yaml"


def _index_entries() -> list[dict[str, object]]:
    data = yaml.safe_load(_INDEX_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("templates") or [])


def _ids(entry: dict[str, object]) -> str:
    value = entry.get("slug", "unknown")
    return str(value)


def _install_template(entry: dict[str, object], workspace: BridgeWorkspace) -> Path:
    """Copy the template's files into the workspace and return the YAML path."""
    yaml_in_workspace: Path | None = None
    for spec in entry.get("files") or []:
        if not isinstance(spec, dict):
            continue
        src_rel = spec.get("src")
        dst_rel = spec.get("dst")
        if not src_rel or not dst_rel:
            continue
        src = _TEMPLATES_ROOT / src_rel
        dst = workspace.root / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if dst.suffix == ".yaml" and yaml_in_workspace is None:
            yaml_in_workspace = dst
    assert yaml_in_workspace is not None, f"template {entry!r} shipped no YAML file"
    return yaml_in_workspace


def _ensure_local_entrypoint(yaml_path: Path, workspace: BridgeWorkspace) -> None:
    """For source=local templates, drop a clean main.py next to the YAML."""
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    build = doc.get("build", {}) or {}
    if build.get("source") != "local":
        return
    entrypoint = build.get("entrypoint") or "main.py"
    # Resolve against the same candidates builder._run_local_source checks:
    # <generated>/<name>/<entrypoint>, <yaml_dir>/<name>/<entrypoint>,
    # <yaml_dir>/<entrypoint>. The last one is the simplest to satisfy.
    target = yaml_path.parent / entrypoint
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HELLO_MAIN_PY, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", _index_entries(), ids=_ids)
def test_dry_run_every_bundled_template(
    entry: dict[str, object],
    tmp_bridge_workspace: BridgeWorkspace,
    mock_xai_client: MockXAIClient,
) -> None:
    yaml_path = _install_template(entry, tmp_bridge_workspace)
    _ensure_local_entrypoint(yaml_path, tmp_bridge_workspace)

    result = run_bridge(yaml_path, dry_run=True, client=mock_xai_client)

    assert isinstance(result, BridgeResult)
    assert result.success is True
    # Every template must produce a generated dir.
    assert result.generated_path is not None and result.generated_path.is_dir()
    # Safety scan must have produced a report.
    assert result.safety_report is not None
    # Every template in the bundle is designed to pass the static scan;
    # the LLM side is fully mocked to return "no risks".
    assert result.safety_report.safe, (
        f"{entry['slug']} produced safety issues: {result.safety_report.issues}"
    )
    # Dry run → no deploy_url was recorded.
    assert result.deploy_url is None


def test_dry_run_non_dry_deploy_fills_url(
    tmp_bridge_workspace: BridgeWorkspace,
    mock_xai_client: MockXAIClient,
    minimal_bridge_yaml: str,
    hello_main_py: str,
) -> None:
    """End-to-end with dry_run=False still exits cleanly on a local target."""
    tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    tmp_bridge_workspace.write_entrypoint("main.py", hello_main_py)
    result = run_bridge(
        tmp_bridge_workspace.yaml_path,
        dry_run=False,
        client=mock_xai_client,
    )
    assert result.success is True
    assert result.deploy_target == "local"
    assert result.deploy_url is not None
    assert "minimal-test-bot" in str(result.deploy_url)


def test_grok_source_uses_stream_chat(
    tmp_bridge_workspace: BridgeWorkspace,
    mock_xai_client: MockXAIClient,
    grok_bridge_yaml: str,
) -> None:
    """With source=grok the mock's stream_chat is the one servicing the build."""
    tmp_bridge_workspace.write_bridge(grok_bridge_yaml)
    result = run_bridge(
        tmp_bridge_workspace.yaml_path,
        dry_run=True,
        client=mock_xai_client,
    )
    assert result.success
    assert any(c["method"] == "stream_chat" for c in mock_xai_client.calls)
    # Plus one single_call for the safety-scan LLM audit.
    assert any(c["method"] == "single_call" for c in mock_xai_client.calls)
