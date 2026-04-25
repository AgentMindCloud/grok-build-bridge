"""Tests for :mod:`grok_build_bridge.publish`.

Covers manifest construction, schema validation, zip output, and the
``--dry-run`` short-circuit. No network IO; nothing here touches the
future grokagents.dev endpoint — by design, the publish layer stops at
disk in v0.2.x.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import jsonschema
import pytest

from grok_build_bridge.parser import BridgeConfigError
from grok_build_bridge.publish import (
    PublishResult,
    build_manifest,
    publish,
)
from tests.conftest import BridgeWorkspace

# ---------------------------------------------------------------------------
# build_manifest — pure function, no IO
# ---------------------------------------------------------------------------


def _example_config() -> dict[str, object]:
    return {
        "version": "1.0",
        "name": "publish-test-bot",
        "description": "Demo agent used by the publish tests.",
        "build": {
            "source": "grok",
            "language": "python",
            "entrypoint": "main.py",
            "required_tools": ["x_search"],
            "grok_prompt": "Read XAI_API_KEY and X_BEARER_TOKEN and post a thread.",
        },
        "deploy": {"target": "x", "schedule": "0 13 * * 1"},
        "agent": {"model": "grok-4.20-0309"},
        "safety": {"audit_before_post": True, "lucas_veto_enabled": True},
    }


def test_build_manifest_pins_schema_version_and_required_blocks(tmp_path: Path) -> None:
    manifest = build_manifest(
        _example_config(), version="1.2.3", bridge_path=tmp_path / "bridge.yaml"
    )
    assert manifest["schema_version"] == "1.0"
    assert manifest["name"] == "publish-test-bot"
    assert manifest["version"] == "1.2.3"
    assert manifest["bridge"]["target"] == "x"
    assert manifest["bridge"]["model"] == "grok-4.20-0309"
    assert manifest["bridge"]["required_tools"] == ["x_search"]
    assert manifest["bridge"]["schedule"] == "0 13 * * 1"
    # X target → both core env vars are surfaced.
    assert manifest["bridge"]["required_env"] == ["XAI_API_KEY", "X_BEARER_TOKEN"]


def test_build_manifest_emits_safety_block_from_bridge_config(tmp_path: Path) -> None:
    manifest = build_manifest(
        _example_config(), version="0.1.0", bridge_path=tmp_path / "bridge.yaml"
    )
    assert manifest["safety"]["lucas_veto_enabled"] is True
    assert manifest["safety"]["audit_status"] == "passed"


def test_build_manifest_falls_back_to_unknown_author(tmp_path: Path) -> None:
    manifest = build_manifest(
        _example_config(), version="0.1.0", bridge_path=tmp_path / "bridge.yaml"
    )
    assert manifest["author"] == {"name": "Unknown"}
    assert manifest["license"] == "Apache-2.0"


def test_build_manifest_honours_overrides(tmp_path: Path) -> None:
    manifest = build_manifest(
        _example_config(),
        version="0.1.0",
        bridge_path=tmp_path / "bridge.yaml",
        author_overrides={"name": "Jan Solo", "email": "jan@agentmind.cloud", "x": "@JanSol0s"},
        license_id="MIT",
        homepage="https://example.test/agent",
        repository="https://github.com/example/agent",
        categories=["research", "x-deploy"],
        keywords=["weekly", "thread"],
    )
    assert manifest["author"]["x"] == "@JanSol0s"
    assert manifest["license"] == "MIT"
    assert manifest["homepage"] == "https://example.test/agent"
    assert manifest["categories"] == ["research", "x-deploy"]
    assert manifest["keywords"] == ["thread", "weekly"]  # sorted


def test_build_manifest_for_railway_target_only_lists_xai_key(tmp_path: Path) -> None:
    cfg = _example_config()
    cfg["deploy"] = {"target": "railway"}
    cfg["build"]["grok_prompt"] = ""
    manifest = build_manifest(cfg, version="0.1.0", bridge_path=tmp_path / "bridge.yaml")
    assert manifest["bridge"]["target"] == "railway"
    assert manifest["bridge"]["required_env"] == ["XAI_API_KEY"]


# ---------------------------------------------------------------------------
# publish — end-to-end
# ---------------------------------------------------------------------------


def test_publish_dry_run_validates_without_writing_zip(
    tmp_bridge_workspace: BridgeWorkspace, minimal_bridge_yaml: str
) -> None:
    bridge = tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    result = publish(bridge, version="0.1.0", dry_run=True)
    assert isinstance(result, PublishResult)
    assert result.dry_run is True
    assert result.package_path is None
    # Manifest should be schema-valid even without the package block.
    schema = _schema()
    jsonschema.validate(result.manifest, schema)


def test_publish_writes_zip_with_manifest_and_bridge_yaml(
    tmp_bridge_workspace: BridgeWorkspace, minimal_bridge_yaml: str
) -> None:
    bridge = tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    out_dir = tmp_bridge_workspace.root / "dist" / "marketplace"
    result = publish(bridge, version="0.1.0", out_dir=out_dir)

    assert result.package_path is not None
    assert result.package_path.is_file()
    assert result.package_path.name == "minimal-test-bot-0.1.0.zip"

    with zipfile.ZipFile(result.package_path) as zf:
        names = sorted(zf.namelist())
        assert "manifest.json" in names
        assert "bridge.yaml" in names

        # The manifest inside the zip should match the in-memory manifest exactly,
        # including the package block (which is patched after the digest is known).
        zip_manifest = json.loads(zf.read("manifest.json"))

    assert zip_manifest == result.manifest
    assert zip_manifest["package"]["files"] == ["bridge.yaml", "manifest.json"]
    assert zip_manifest["package"]["size_bytes"] > 0
    assert len(zip_manifest["package"]["sha256"]) == 64


def test_publish_marketplace_block_defaults_to_draft(
    tmp_bridge_workspace: BridgeWorkspace, minimal_bridge_yaml: str
) -> None:
    bridge = tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    result = publish(bridge, version="0.2.0", dry_run=True)
    mkt = result.manifest["marketplace"]
    assert mkt["status"] == "draft"
    assert mkt["published_at"] is None
    assert mkt["registry_url"].endswith("/minimal-test-bot")


def test_publish_include_build_bundles_generated_dir(
    tmp_bridge_workspace: BridgeWorkspace, minimal_bridge_yaml: str
) -> None:
    bridge = tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    # Simulate a previous bridge run by dropping a generated/<slug>/ tree.
    gen = tmp_bridge_workspace.root / "generated" / "minimal-test-bot"
    gen.mkdir(parents=True)
    (gen / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (gen / "bridge.manifest.json").write_text(
        json.dumps({"name": "minimal-test-bot", "token_usage_estimate": 1234}),
        encoding="utf-8",
    )

    result = publish(bridge, version="0.1.0", include_build=True)
    assert result.package_path is not None
    with zipfile.ZipFile(result.package_path) as zf:
        names = sorted(zf.namelist())
    assert "minimal-test-bot/main.py" in names
    assert "minimal-test-bot/bridge.manifest.json" in names
    # Token estimate from the build manifest should propagate into the marketplace manifest.
    assert result.manifest["bridge"]["estimated_tokens"] == 1234


def test_publish_rejects_missing_bridge_yaml(tmp_path: Path) -> None:
    with pytest.raises(BridgeConfigError, match="bridge YAML not found"):
        publish(tmp_path / "does-not-exist.yaml", version="0.1.0", dry_run=True)


def test_publish_rejects_invalid_semver(
    tmp_bridge_workspace: BridgeWorkspace, minimal_bridge_yaml: str
) -> None:
    bridge = tmp_bridge_workspace.write_bridge(minimal_bridge_yaml)
    with pytest.raises(BridgeConfigError, match="schema validation"):
        publish(bridge, version="not-a-semver", dry_run=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema() -> dict[str, object]:
    here = Path(__file__).resolve().parent.parent
    return json.loads((here / "marketplace" / "manifest.schema.json").read_text(encoding="utf-8"))
