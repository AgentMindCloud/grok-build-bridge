"""Publish layer — package a built agent for the future grokagents.dev marketplace.

Produces a forward-compatible artefact that the registry consumes once it
ships. Today the command stops at writing the zip + manifest to disk; an
``--upload`` flag will be added in a follow-up release once the registry
API exists. The marketplace contract lives in ``marketplace/manifest.schema.json``;
this module is the only writer that file in the repository.

Workflow:

1. Load + validate ``bridge.yaml`` (reusing :func:`grok_build_bridge.parser.load_yaml`).
2. Build a marketplace manifest from the bridge config and any sibling
   ``bridge.manifest.json`` written by :mod:`grok_build_bridge.builder`.
3. Validate the manifest against ``marketplace/manifest.schema.json``.
4. Write a zip to ``dist/marketplace/<slug>-<version>.zip`` containing
   ``manifest.json`` plus ``bridge.yaml``. If ``--include-build`` is set
   and a ``generated/<slug>/`` directory exists, also bundle its files.
5. Patch the manifest's ``package.{files, size_bytes, sha256}`` block with
   the actual zip metadata so the file in the zip and the file the
   registry receives describe the same artefact.

Forward-compat notes:
  * ``schema_version`` is pinned to ``"1.0"``. Future versions bump this.
  * Optional fields (``safety``, ``package``, ``marketplace``,
    ``categories``, ``keywords``) can be empty in v1.0 packages.
  * No network IO. ``--upload`` will land in v0.3.0.
"""

from __future__ import annotations

import hashlib
import importlib.resources as resources
import json
import logging
import zipfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from jsonschema import Draft202012Validator, ValidationError

from grok_build_bridge.parser import BridgeConfigError, load_yaml

logger: Final[logging.Logger] = logging.getLogger(__name__)

_MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"
_MANIFEST_FILENAME: Final[str] = "manifest.json"
_BRIDGE_MANIFEST_FILENAME: Final[str] = "bridge.manifest.json"
_DEFAULT_OUT_DIR: Final[Path] = Path("dist") / "marketplace"
_DEFAULT_REGISTRY_BASE: Final[str] = "https://grokagents.dev/agents"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class PublishResult:
    """Outcome of a :func:`publish` run.

    Attributes:
        manifest:    The validated manifest dict (also written into the zip).
        package_path: Path to the written zip, or ``None`` for ``--dry-run``.
        dry_run:     ``True`` if no zip was written.
    """

    __slots__ = ("manifest", "package_path", "dry_run")

    def __init__(
        self,
        *,
        manifest: dict[str, Any],
        package_path: Path | None,
        dry_run: bool,
    ) -> None:
        self.manifest = manifest
        self.package_path = package_path
        self.dry_run = dry_run


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def _load_schema() -> dict[str, Any]:
    """Read ``marketplace/manifest.schema.json`` from the installed package.

    Falls back to the on-disk path during development checkouts where the
    folder is part of the repository but not part of the wheel.
    """
    try:
        # Wheel-installed path: schema bundled as package data (future).
        ref = resources.files("grok_build_bridge").joinpath("marketplace/manifest.schema.json")
        if ref.is_file():
            data: dict[str, Any] = json.loads(ref.read_text(encoding="utf-8"))
            return data
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    # Repo-root fallback for `pip install -e .` / direct checkouts.
    repo_root = Path(__file__).resolve().parent.parent
    schema_path = repo_root / "marketplace" / "manifest.schema.json"
    if not schema_path.is_file():
        raise BridgeConfigError(
            "marketplace/manifest.schema.json is missing — re-install grok-build-bridge or check out the repo from git.",
        )
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def _read_bridge_manifest(generated_dir: Path) -> dict[str, Any]:
    """Read ``bridge.manifest.json`` if a previous build wrote one."""
    candidate = generated_dir / _BRIDGE_MANIFEST_FILENAME
    if not candidate.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(candidate.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError:
        logger.warning("bridge.manifest.json at %s is not valid JSON; ignoring", candidate)
        return {}


def _resolve_generated_dir(bridge_path: Path, slug: str) -> Path:
    """Find the directory builder.py last wrote to (best-effort).

    Search order:
      1. ``./generated/<slug>``  — the builder's default
      2. ``<bridge_path.parent>/generated/<slug>``
      3. ``<bridge_path.parent>/<slug>`` — the `init` template layout
    Returns the first match; otherwise the conventional default even if
    it does not exist (callers handle the missing case).
    """
    candidates = [
        Path("generated") / slug,
        bridge_path.parent / "generated" / slug,
        bridge_path.parent / slug,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def build_manifest(
    config: dict[str, Any],
    *,
    version: str,
    bridge_path: Path,
    author_overrides: dict[str, Any] | None = None,
    license_id: str | None = None,
    homepage: str | None = None,
    repository: str | None = None,
    categories: Iterable[str] | None = None,
    keywords: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a marketplace manifest dict from a validated bridge config.

    The result is *unvalidated* — :func:`publish` runs the schema check.
    Splitting these lets tests assert on the manifest shape without
    needing a writeable filesystem.
    """
    name = str(config["name"])
    deploy_cfg = dict(config.get("deploy") or {})
    build_cfg = dict(config.get("build") or {})
    agent_cfg = dict(config.get("agent") or {})
    safety_cfg = dict(config.get("safety") or {})

    bridge_block: dict[str, Any] = {
        "model": str(agent_cfg.get("model", "")),
        "target": str(deploy_cfg.get("target", "x")),
        "language": str(build_cfg.get("language", "python")),
    }
    required_tools = list(build_cfg.get("required_tools") or [])
    if required_tools:
        bridge_block["required_tools"] = required_tools

    # Heuristic: surface env vars referenced in the prompt + any X target.
    required_env = _infer_required_env(config)
    if required_env:
        bridge_block["required_env"] = required_env

    schedule = deploy_cfg.get("schedule")
    if schedule:
        bridge_block["schedule"] = str(schedule)

    # Pull token estimate from the build manifest if present.
    generated_dir = _resolve_generated_dir(bridge_path, name)
    build_manifest = _read_bridge_manifest(generated_dir)
    if build_manifest.get("token_usage_estimate"):
        bridge_block["estimated_tokens"] = int(build_manifest["token_usage_estimate"])

    # Safety posture mirrors what the bridge knows at publish time.
    safety_block: dict[str, Any] = {}
    if "audit_before_post" in safety_cfg:
        safety_block["audit_status"] = (
            "passed" if safety_cfg.get("audit_before_post") else "skipped"
        )
    if "lucas_veto_enabled" in safety_cfg:
        safety_block["lucas_veto_enabled"] = bool(safety_cfg["lucas_veto_enabled"])
    safety_block["audited_at"] = datetime.now(timezone.utc).isoformat()

    author = {"name": "Unknown"}
    author.update(author_overrides or {})

    manifest: dict[str, Any] = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "name": name,
        "version": version,
        "description": str(config.get("description") or "").strip()[:280] or name,
        "author": author,
        "license": license_id or "Apache-2.0",
        "bridge": bridge_block,
    }

    if homepage:
        manifest["homepage"] = homepage
    if repository:
        manifest["repository"] = repository
    if categories:
        manifest["categories"] = sorted(set(categories))
    if keywords:
        manifest["keywords"] = sorted(set(keywords))
    if safety_block:
        manifest["safety"] = safety_block

    # `package` and `marketplace` blocks are filled after we know the zip.
    manifest["marketplace"] = {
        "status": "draft",
        "published_at": None,
        "registry_url": f"{_DEFAULT_REGISTRY_BASE}/{name}",
    }
    return manifest


def _infer_required_env(config: dict[str, Any]) -> list[str]:
    """Best-effort scan for env-var names referenced by the bridge config.

    Looks at the `grok_prompt` body and any X-bound deploy targets. We err
    on the side of completeness — listing more vars is harmless; missing
    one is a runtime surprise.
    """
    found: set[str] = set()
    deploy_target = ((config.get("deploy") or {}).get("target")) or "x"
    if deploy_target == "x":
        found.update({"XAI_API_KEY", "X_BEARER_TOKEN"})
    elif deploy_target in {"vercel", "render", "railway", "flyio"}:
        found.add("XAI_API_KEY")

    prompt = ((config.get("build") or {}).get("grok_prompt")) or ""
    for token in _SCAN_ENV_TOKENS:
        if token in prompt:
            found.add(token)
    return sorted(found)


_SCAN_ENV_TOKENS: Final[tuple[str, ...]] = (
    "XAI_API_KEY",
    "X_BEARER_TOKEN",
    "GROK_INSTALL_HOME",
    "TARGET_REPO",
    "BRIDGE_RESEARCH_TOPIC",
    "RAILWAY_PROJECT_ID",
)


# ---------------------------------------------------------------------------
# Zip writer
# ---------------------------------------------------------------------------


def _write_zip(
    *,
    zip_path: Path,
    bridge_path: Path,
    manifest: dict[str, Any],
    include_build: bool,
) -> tuple[list[str], int, str]:
    """Write the package zip; return (files, size_bytes, sha256)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    name = manifest["name"]
    generated_dir = _resolve_generated_dir(bridge_path, name)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. bridge.yaml — always.
        zf.write(bridge_path, arcname="bridge.yaml")
        files.append("bridge.yaml")

        # 2. manifest.json — written from the in-memory dict (with placeholder
        #    package block; we patch + rewrite once we know the real digest).
        zf.writestr(_MANIFEST_FILENAME, json.dumps(manifest, indent=2, sort_keys=True))
        files.append(_MANIFEST_FILENAME)

        # 3. Optional build artefacts.
        if include_build and generated_dir.is_dir():
            for entry in sorted(generated_dir.rglob("*")):
                if entry.is_file():
                    arcname = str(Path(entry.relative_to(generated_dir.parent)))
                    zf.write(entry, arcname=arcname)
                    files.append(arcname)

    size_bytes = zip_path.stat().st_size
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return sorted(set(files)), size_bytes, sha256


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def publish(
    bridge_yaml: str | Path,
    *,
    version: str = "0.1.0",
    out_dir: str | Path | None = None,
    include_build: bool = False,
    dry_run: bool = False,
    author_overrides: dict[str, Any] | None = None,
    license_id: str | None = None,
    homepage: str | None = None,
    repository: str | None = None,
    categories: Iterable[str] | None = None,
    keywords: Iterable[str] | None = None,
) -> PublishResult:
    """📦 Package a built agent for the future grokagents.dev marketplace.

    Args:
        bridge_yaml: Path to the bridge YAML config.
        version: Semantic version of the package (independent of grok-build-bridge).
        out_dir: Where to write the zip. Defaults to ``dist/marketplace/``.
        include_build: When true, include any files under ``generated/<slug>/``.
        dry_run: Build + validate the manifest but do not write the zip.

    Returns:
        :class:`PublishResult` with the validated manifest and the package
        path (or ``None`` for ``--dry-run``).

    Raises:
        BridgeConfigError: On schema/validation failures (exit code 2).
    """
    bridge_path = Path(bridge_yaml).expanduser().resolve()
    if not bridge_path.is_file():
        raise BridgeConfigError(
            f"bridge YAML not found: {bridge_path}. "
            "Pass an existing path, e.g. `grok-build-bridge publish bridge.yaml`.",
        )

    config_proxy = load_yaml(bridge_path)
    config = _unfreeze(config_proxy)

    manifest = build_manifest(
        config,
        version=version,
        bridge_path=bridge_path,
        author_overrides=author_overrides,
        license_id=license_id,
        homepage=homepage,
        repository=repository,
        categories=categories,
        keywords=keywords,
    )

    schema = _load_schema()
    validator = Draft202012Validator(schema)

    if dry_run:
        # Validate the manifest without the package block — schema allows it.
        try:
            validator.validate(manifest)
        except ValidationError as exc:
            raise BridgeConfigError(
                f"manifest failed schema validation: {exc.message}. "
                "Fix the offending field and re-run; --dry-run never writes a zip.",
            ) from exc
        return PublishResult(manifest=manifest, package_path=None, dry_run=True)

    out = Path(out_dir) if out_dir else _DEFAULT_OUT_DIR
    zip_path = out / f"{manifest['name']}-{version}.zip"

    files, size_bytes, sha256 = _write_zip(
        zip_path=zip_path,
        bridge_path=bridge_path,
        manifest=manifest,
        include_build=include_build,
    )

    # Patch the package block now that we know the real digest, then
    # rewrite manifest.json inside the zip so the published file's
    # self-description matches the file the registry receives.
    manifest["package"] = {
        "files": files,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }

    try:
        validator.validate(manifest)
    except ValidationError as exc:
        # Validation runs LAST so the zip already exists; we leave it on
        # disk for inspection but raise so the CLI exits non-zero.
        raise BridgeConfigError(
            f"manifest failed schema validation: {exc.message}. "
            f"Fix the offending field and re-run. Zip left for inspection at {zip_path}.",
        ) from exc

    _replace_manifest_in_zip(zip_path, manifest)

    return PublishResult(manifest=manifest, package_path=zip_path, dry_run=False)


def _unfreeze(value: Any) -> Any:
    """Recursively convert :class:`MappingProxyType` / tuples back to mutable dicts/lists.

    The parser returns frozen views so accidental mutation of the cached
    config cannot leak between phases. The publish layer needs a mutable
    dict to slot in the patched ``package`` block, so we copy here and
    nowhere else.
    """
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        return {k: _unfreeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unfreeze(v) for v in value]
    return value


def _replace_manifest_in_zip(zip_path: Path, manifest: dict[str, Any]) -> None:
    """Rewrite ``manifest.json`` inside an existing zip without re-zipping anything else."""
    # zipfile cannot replace a member in place; rewrite the whole archive
    # but keep deflate-level identical so the digest only depends on
    # manifest contents + bridge.yaml + (optional) build outputs.
    tmp = zip_path.with_suffix(zip_path.suffix + ".tmp")
    with (
        zipfile.ZipFile(zip_path, "r") as src,
        zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            if item.filename == _MANIFEST_FILENAME:
                dst.writestr(item, json.dumps(manifest, indent=2, sort_keys=True))
            else:
                dst.writestr(item, src.read(item.filename))
    tmp.replace(zip_path)


__all__ = [
    "PublishResult",
    "build_manifest",
    "publish",
]
