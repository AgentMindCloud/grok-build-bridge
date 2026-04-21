"""Parser and schema tests for ``grok_build_bridge.parser``."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from grok_build_bridge.parser import (
    BridgeConfigError,
    load_yaml,
    validate,
)


def _minimal_config() -> dict[str, Any]:
    """Smallest document the schema accepts (all required keys present)."""
    return {
        "version": "1.0",
        "name": "minimal-bot",
        "description": "A tiny test agent.",
        "build": {"source": "local"},
        "deploy": {},
        "agent": {"model": "grok-4.20-0309"},
    }


def _full_config() -> dict[str, Any]:
    """Every optional key populated so we exercise the whole schema surface."""
    return {
        "version": "1.0",
        "name": "full-bot",
        "description": "Full config covering every optional field in the schema.",
        "build": {
            "source": "grok",
            "grok_prompt": "Build a bot that posts haikus about Linux kernels.",
            "language": "typescript",
            "entrypoint": "src/main.ts",
            "required_tools": ["x_search", "web_search"],
        },
        "deploy": {
            "target": "vercel",
            "runtime": "vercel-edge",
            "post_to_x": True,
            "safety_scan": False,
            "schedule": "0 */6 * * *",
        },
        "agent": {
            "model": "grok-4.20-multi-agent-0309",
            "reasoning_effort": "xhigh",
            "personality": "wry, terse, vaguely cosmic",
        },
        "safety": {
            "audit_before_post": True,
            "max_tokens_per_run": 50_000,
            "lucas_veto_enabled": True,
        },
    }


def _write_yaml(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "bridge.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_valid_minimal_yaml_loads_and_freezes(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, _minimal_config())
    cfg = load_yaml(path)

    assert isinstance(cfg, MappingProxyType)
    assert cfg["name"] == "minimal-bot"
    # Frozen: top-level mutation is a TypeError, not silent success.
    with pytest.raises(TypeError):
        cfg["name"] = "other"  # type: ignore[index]
    # Nested mappings are also frozen.
    with pytest.raises(TypeError):
        cfg["build"]["source"] = "grok"  # type: ignore[index]


def test_valid_full_yaml_preserves_all_fields(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, _full_config())
    cfg = load_yaml(path)

    assert cfg["build"]["required_tools"] == ("x_search", "web_search")
    assert cfg["deploy"]["schedule"] == "0 */6 * * *"
    assert cfg["safety"]["max_tokens_per_run"] == 50_000
    assert cfg["agent"]["reasoning_effort"] == "xhigh"


def test_defaults_are_applied(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, _minimal_config())
    cfg = load_yaml(path)

    # build defaults
    assert cfg["build"]["language"] == "python"
    assert cfg["build"]["entrypoint"] == "main.py"
    # deploy defaults
    assert cfg["deploy"]["target"] == "x"
    assert cfg["deploy"]["runtime"] == "grok-install"
    assert cfg["deploy"]["post_to_x"] is False
    assert cfg["deploy"]["safety_scan"] is True
    # agent default
    assert cfg["agent"]["reasoning_effort"] == "medium"


def test_entrypoint_default_follows_language(tmp_path: Path) -> None:
    doc = _minimal_config()
    doc["build"] = {"source": "local", "language": "go"}
    path = _write_yaml(tmp_path, doc)
    cfg = load_yaml(path)

    assert cfg["build"]["entrypoint"] == "main.go"


def test_schedule_string_is_preserved_verbatim(tmp_path: Path) -> None:
    doc = _minimal_config()
    doc["deploy"] = {"schedule": "*/15 * * * *"}
    path = _write_yaml(tmp_path, doc)
    cfg = load_yaml(path)

    assert cfg["deploy"]["schedule"] == "*/15 * * * *"


@pytest.mark.parametrize(
    ("mutator", "expected_key"),
    [
        pytest.param(
            lambda d: d.pop("name"),
            "name",
            id="missing-name",
        ),
        pytest.param(
            lambda d: d["agent"].__setitem__("model", "grok-4"),
            "model",
            id="invalid-model-enum",
        ),
        pytest.param(
            lambda d: d.__setitem__("name", "Bad Name!"),
            "name",
            id="bad-slug",
        ),
        pytest.param(
            lambda d: d.__setitem__("version", "2.0"),
            "version",
            id="unsupported-schema-version",
        ),
        pytest.param(
            lambda d: (
                d["build"].__setitem__("source", "local")
                or d["build"].__setitem__("language", "rust")
            ),
            "language",
            id="unsupported-language",
        ),
        pytest.param(
            lambda d: (
                d["safety"].__setitem__("max_tokens_per_run", 10)
                if "safety" in d
                else d.__setitem__("safety", {"max_tokens_per_run": 10})
            ),
            "max_tokens_per_run",
            id="max-tokens-below-minimum",
        ),
    ],
)
def test_invalid_documents_raise_bridge_config_error(
    tmp_path: Path,
    mutator: Any,
    expected_key: str,
) -> None:
    doc = _full_config()
    mutator(doc)
    path = _write_yaml(tmp_path, doc)

    with pytest.raises(BridgeConfigError) as excinfo:
        load_yaml(path)

    # key_path ends at the offending property so downstream tools can jump
    # straight to it without re-parsing the jsonschema message.
    assert excinfo.value.key_path, "key_path should not be empty for a schema error"
    assert (
        expected_key in {str(p) for p in excinfo.value.key_path}
        or str(excinfo.value.key_path[-1]) == expected_key
    )


def test_additional_properties_rejected(tmp_path: Path) -> None:
    doc = _minimal_config()
    doc["surprise"] = "boo"
    path = _write_yaml(tmp_path, doc)

    with pytest.raises(BridgeConfigError) as excinfo:
        load_yaml(path)
    assert "surprise" in excinfo.value.message


def test_additional_properties_rejected_nested(tmp_path: Path) -> None:
    doc = _minimal_config()
    doc["build"]["lol"] = True
    path = _write_yaml(tmp_path, doc)

    with pytest.raises(BridgeConfigError) as excinfo:
        load_yaml(path)
    assert "lol" in excinfo.value.message


def test_grok_source_requires_prompt(tmp_path: Path) -> None:
    doc = _minimal_config()
    doc["build"] = {"source": "grok"}  # no grok_prompt
    path = _write_yaml(tmp_path, doc)

    with pytest.raises(BridgeConfigError):
        load_yaml(path)


def test_syntax_error_reports_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "bridge.yaml"
    path.write_text("version: '1.0'\nname: [unterminated\n", encoding="utf-8")

    with pytest.raises(BridgeConfigError) as excinfo:
        load_yaml(path)
    assert excinfo.value.line is not None
    assert excinfo.value.column is not None


def test_missing_file_raises_bridge_config_error(tmp_path: Path) -> None:
    with pytest.raises(BridgeConfigError):
        load_yaml(tmp_path / "does-not-exist.yaml")


def test_non_mapping_root_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bridge.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(BridgeConfigError):
        load_yaml(path)


def test_validate_is_pure_standalone() -> None:
    doc = _minimal_config()
    # validate() must not mutate or fill defaults.
    validate(doc)
    assert "language" not in doc["build"]
    assert "target" not in doc["deploy"]


def test_validate_raises_on_invalid_doc() -> None:
    doc = _minimal_config()
    doc["agent"]["model"] = "not-a-real-model"
    with pytest.raises(BridgeConfigError):
        validate(doc)


def test_error_render_highlights_key_path(capsys: pytest.CaptureFixture[str]) -> None:
    err = BridgeConfigError(
        "fake problem",
        key_path=["build", "source"],
        expected="one of ['grok', 'local', 'grok-build-cli']",
        line=4,
        column=9,
        source_path="bridge.yaml",
    )
    from rich.console import Console

    console = Console(file=None, force_terminal=False, width=80)
    err.render(console=console)
    captured = capsys.readouterr()
    # Rich is writing via our console to stdout; just check the pieces are there.
    out = captured.out + captured.err
    assert "build.source" in out
    assert "fake problem" in out
    assert "line 4" in out
