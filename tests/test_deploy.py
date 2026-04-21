"""Tests for :mod:`grok_build_bridge.deploy`.

Exercises each deploy target dispatch + the pre-deploy X-post audit gate.
Network access is never attempted — ``shutil.which`` is monkeypatched so
the tests can pretend the ``vercel`` CLI is or isn't installed without
touching the real $PATH.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from grok_build_bridge import deploy as deploy_mod
from grok_build_bridge.deploy import (
    _deploy_local,
    _deploy_render,
    _deploy_vercel,
    _dry_run_stub,
    _read_manifest,
    _run_x_audit,
    deploy_to_target,
)
from grok_build_bridge.safety import BridgeSafetyError, SafetyReport
from grok_build_bridge.xai_client import BridgeRuntimeError
from tests.conftest import MockXAIClient


def _base_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "name": "deploy-test",
        "description": "Deploy-test description.",
        "build": {"source": "local", "language": "python", "entrypoint": "main.py"},
        "deploy": {"target": "local"},
        "agent": {"model": "grok-4.20-0309"},
        "safety": {"audit_before_post": False},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# _dry_run_stub
# ---------------------------------------------------------------------------


def test_dry_run_stub_writes_payload_and_returns_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = {"hello": "world"}
    result = _dry_run_stub(payload)
    assert result == {"dry_run": True, "path": "generated/deploy_payload.json"}
    written = json.loads((tmp_path / "generated" / "deploy_payload.json").read_text())
    assert written == {"hello": "world"}


# ---------------------------------------------------------------------------
# _deploy_vercel
# ---------------------------------------------------------------------------


def test_deploy_vercel_without_binary_prints_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("grok_build_bridge.deploy.shutil.which", lambda _: None)
    cfg = _base_config()
    url = _deploy_vercel(tmp_path, cfg)
    assert url == f"vercel://pending/{cfg['name']}"


def test_deploy_vercel_with_binary_returns_last_stdout_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("grok_build_bridge.deploy.shutil.which", lambda _: "/fake/vercel")

    class _Completed:
        stdout = "Preview: https://x.example\nhttps://prod.example\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(
        "grok_build_bridge.deploy.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    url = _deploy_vercel(tmp_path, _base_config())
    assert url == "https://prod.example"


def test_deploy_vercel_raises_on_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("grok_build_bridge.deploy.shutil.which", lambda _: "/fake/vercel")

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, "vercel", stderr="login required")

    monkeypatch.setattr("grok_build_bridge.deploy.subprocess.run", _boom)
    with pytest.raises(BridgeRuntimeError, match="vercel deploy failed"):
        _deploy_vercel(tmp_path, _base_config())


# ---------------------------------------------------------------------------
# _deploy_render
# ---------------------------------------------------------------------------


def test_deploy_render_writes_render_yaml(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "render", "schedule": "0 9 * * *"}
    cfg["build"] = {"source": "local", "language": "python", "entrypoint": "main.py"}
    url = _deploy_render(tmp_path, cfg)
    rendered = (tmp_path / "render.yaml").read_text(encoding="utf-8")
    assert "schedule: '0 9 * * *'" in rendered
    assert "startCommand: python main.py" in rendered
    assert url.startswith("render://pending/")


def test_deploy_render_typescript_entrypoint(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["build"] = {"source": "local", "language": "typescript", "entrypoint": "index.ts"}
    _deploy_render(tmp_path, cfg)
    rendered = (tmp_path / "render.yaml").read_text(encoding="utf-8")
    assert "startCommand: node index.ts" in rendered


# ---------------------------------------------------------------------------
# _deploy_local
# ---------------------------------------------------------------------------


def test_deploy_local_returns_generated_dir(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["build"] = {"source": "local", "language": "go", "entrypoint": "main.go"}
    url = _deploy_local(tmp_path, cfg)
    assert url == str(tmp_path)


# ---------------------------------------------------------------------------
# _read_manifest
# ---------------------------------------------------------------------------


def test_read_manifest_returns_empty_when_file_absent(tmp_path: Path) -> None:
    assert _read_manifest(tmp_path) == {}


def test_read_manifest_returns_parsed_json(tmp_path: Path) -> None:
    (tmp_path / "bridge.manifest.json").write_text(json.dumps({"name": "x"}))
    assert _read_manifest(tmp_path) == {"name": "x"}


def test_read_manifest_raises_on_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "bridge.manifest.json").write_text("not json")
    with pytest.raises(BridgeRuntimeError, match="not valid JSON"):
        _read_manifest(tmp_path)


# ---------------------------------------------------------------------------
# _run_x_audit
# ---------------------------------------------------------------------------


def test_run_x_audit_skips_when_no_content(mock_xai_client: MockXAIClient) -> None:
    cfg = _base_config()
    cfg["description"] = ""
    # No exception means the audit short-circuited.
    _run_x_audit(cfg, client=mock_xai_client)


def test_run_x_audit_skips_when_gates_off(mock_xai_client: MockXAIClient) -> None:
    cfg = _base_config()
    cfg["safety"] = {"audit_before_post": False, "lucas_veto_enabled": False}
    _run_x_audit(cfg, client=mock_xai_client)
    # The mock was not invoked because audit_before_post and lucas_veto both off.
    assert not any(c["method"] == "single_call" for c in mock_xai_client.calls)


def test_run_x_audit_passes_when_safe(mock_xai_client: MockXAIClient) -> None:
    cfg = _base_config()
    cfg["safety"] = {"audit_before_post": True}
    _run_x_audit(cfg, client=mock_xai_client)
    assert any(c["method"] == "single_call" for c in mock_xai_client.calls)


def test_run_x_audit_blocks_when_audit_flags_unsafe(
    monkeypatch: pytest.MonkeyPatch, mock_xai_client: MockXAIClient
) -> None:
    cfg = _base_config()
    cfg["safety"] = {"audit_before_post": True}

    def _fake_audit(content: str, config: dict[str, Any], *, client: Any) -> SafetyReport:
        return SafetyReport(safe=False, score=0.1, issues=["not brand-safe"])

    monkeypatch.setattr("grok_build_bridge.deploy.audit_x_post", _fake_audit)
    with pytest.raises(BridgeSafetyError, match="blocked the launch"):
        _run_x_audit(cfg, client=mock_xai_client)


# ---------------------------------------------------------------------------
# deploy_to_target (dispatch)
# ---------------------------------------------------------------------------


def test_deploy_to_target_local(tmp_path: Path) -> None:
    cfg = _base_config()
    assert deploy_to_target(tmp_path, cfg) == str(tmp_path)


def test_deploy_to_target_unknown_raises(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "banana"}
    with pytest.raises(BridgeRuntimeError, match="unknown deploy.target"):
        deploy_to_target(tmp_path, cfg)


def test_deploy_to_target_x_uses_stub_when_no_grok_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_xai_client: MockXAIClient
) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "x"}
    cfg["safety"] = {"audit_before_post": False}

    # Force the stub deploy_to_x path regardless of whether grok_install is importable.
    called: list[dict[str, Any]] = []

    def _fake_deploy(payload: dict[str, Any]) -> dict[str, Any]:
        called.append(payload)
        return {"url": "https://x.example/deploy-test"}

    monkeypatch.setattr(deploy_mod, "deploy_to_x", _fake_deploy)
    url = deploy_to_target(tmp_path, cfg, client=mock_xai_client)
    assert url == "https://x.example/deploy-test"
    assert called and called[0]["name"] == "deploy-test"


def test_deploy_to_target_x_normalises_non_dict_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_xai_client: MockXAIClient
) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "x"}
    cfg["safety"] = {"audit_before_post": False}
    monkeypatch.setattr(deploy_mod, "deploy_to_x", lambda payload: None)
    url = deploy_to_target(tmp_path, cfg, client=mock_xai_client)
    # When the stub returns None, fall back to an x:// URL built from the name.
    assert url.startswith("x://")


def test_deploy_to_target_vercel_without_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "vercel"}
    monkeypatch.setattr("grok_build_bridge.deploy.shutil.which", lambda _: None)
    url = deploy_to_target(tmp_path, cfg)
    assert url.startswith("vercel://pending/")


def test_deploy_to_target_render(tmp_path: Path) -> None:
    cfg = _base_config()
    cfg["deploy"] = {"target": "render"}
    cfg["build"]["language"] = "python"
    url = deploy_to_target(tmp_path, cfg)
    assert url.startswith("render://pending/")
    assert (tmp_path / "render.yaml").is_file()
