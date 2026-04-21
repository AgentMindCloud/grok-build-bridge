"""Every bundled template file is schema-valid and registered in INDEX.yaml."""

from __future__ import annotations

import importlib.resources as resources
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from grok_build_bridge.parser import load_yaml

_SCHEMA_PATH = Path(__file__).parent.parent / "grok_build_bridge" / "schema" / "bridge.schema.json"
_TEMPLATES_ROOT = Path(__file__).parent.parent / "grok_build_bridge" / "templates"


def _load_schema() -> dict[str, Any]:
    import json

    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _load_index() -> dict[str, Any]:
    index_path = _TEMPLATES_ROOT / "INDEX.yaml"
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    return data  # type: ignore[no-any-return]


def _iter_bridge_yaml_paths() -> list[Path]:
    """Every ``*.yaml`` under templates/ that is NOT INDEX.yaml or a template.yaml."""
    paths: list[Path] = []
    for path in _TEMPLATES_ROOT.rglob("*.yaml"):
        if path.name in {"INDEX.yaml", "template.yaml"}:
            continue
        paths.append(path)
    return sorted(paths)


# ---------------------------------------------------------------------------
# Template → schema validity
# ---------------------------------------------------------------------------


def test_templates_root_exists() -> None:
    assert _TEMPLATES_ROOT.is_dir(), f"missing templates root: {_TEMPLATES_ROOT}"


def test_index_file_parses_and_has_entries() -> None:
    index = _load_index()
    assert index.get("version") == "1.0"
    entries = index.get("templates") or []
    assert isinstance(entries, list) and entries, "INDEX.yaml has no templates entries"
    # Each entry must carry the keys the CLI and docs advertise.
    for entry in entries:
        for required in (
            "name",
            "slug",
            "description",
            "required_env",
            "estimated_tokens",
            "categories",
            "files",
        ):
            assert required in entry, f"INDEX entry {entry!r} missing {required!r}"


def _thaw(value: Any) -> Any:
    """Recursively unfreeze MappingProxyType/tuple structures for jsonschema."""
    from types import MappingProxyType

    if isinstance(value, (dict, MappingProxyType)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


@pytest.mark.parametrize("path", _iter_bridge_yaml_paths(), ids=lambda p: p.name)
def test_every_template_file_passes_bridge_schema(path: Path) -> None:
    """Each shipped bridge YAML validates against the Draft 2020-12 schema."""
    # ``load_yaml`` re-reads the schema AND applies defaults — exactly the
    # code path the CLI uses when a user runs ``grok-build-bridge run``.
    cfg = load_yaml(path)
    assert cfg["name"]
    assert cfg["build"]["source"] in {"grok", "local", "grok-build-cli"}

    # Also run the pure schema validator for belt-and-braces — catches any
    # default-filling side effects that might mask a schema violation.
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(_thaw(cfg)),
        key=lambda e: list(e.absolute_path),
    )
    assert errors == [], f"{path} failed schema: {[e.message for e in errors]}"


# ---------------------------------------------------------------------------
# INDEX ↔ filesystem cross-checks
# ---------------------------------------------------------------------------


def test_every_top_level_template_yaml_has_index_entry() -> None:
    """Every ``*.yaml`` directly under templates/ (except INDEX) must appear in INDEX files."""
    index = _load_index()
    registered_srcs: set[str] = set()
    for entry in index.get("templates", []):
        for spec in entry.get("files") or []:
            if isinstance(spec, dict) and spec.get("src"):
                registered_srcs.add(str(spec["src"]))

    top_level_yamls = [p for p in _TEMPLATES_ROOT.iterdir() if p.is_file() and p.suffix == ".yaml"]
    for path in top_level_yamls:
        if path.name == "INDEX.yaml":
            continue
        rel = path.name
        assert rel in registered_srcs, f"{rel} exists on disk but is not referenced from INDEX.yaml"


def test_every_index_file_exists_on_disk() -> None:
    """Every INDEX file src must resolve to a real file in the templates tree."""
    index = _load_index()
    for entry in index.get("templates", []):
        for spec in entry.get("files") or []:
            src = spec.get("src") if isinstance(spec, dict) else None
            if not src:
                continue
            resolved = _TEMPLATES_ROOT / src
            assert resolved.is_file(), (
                f"INDEX references {src!r} but file does not exist at {resolved}"
            )


def test_slug_matches_filename_for_flat_templates() -> None:
    """Flat-style templates (single file) should have ``slug == stem of the YAML``."""
    index = _load_index()
    for entry in index.get("templates", []):
        files = entry.get("files") or []
        if len(files) != 1:
            continue
        src = files[0].get("src")
        if not src or "/" in src:
            continue  # nested template; slug may diverge
        slug = entry.get("slug")
        stem = Path(src).stem
        assert slug == stem, f"slug {slug!r} should match YAML stem {stem!r}"


def test_templates_package_ships_schema_and_index() -> None:
    """Both schema and INDEX.yaml are reachable via importlib.resources."""
    schema_res = resources.files("grok_build_bridge.schema") / "bridge.schema.json"
    assert schema_res.is_file()
    index_res = resources.files("grok_build_bridge.templates") / "INDEX.yaml"
    assert index_res.is_file()
