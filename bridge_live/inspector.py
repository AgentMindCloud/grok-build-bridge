"""YAML → :class:`Passport` distilation.

Wraps :func:`grok_build_bridge.parser.load_yaml` (parse + schema-validate
+ defaults) and the static-only half of
:func:`grok_build_bridge.safety.scan_generated_code` to produce a
:class:`bridge_live.store.Passport` without ever calling Grok or
touching a deploy hook.

That decision is the whole reason ``bridge.live`` is cheap to host:
no XAI key, no token spend, no rate-limit risk, just a static read of
the schema + a regex pass over any local code that ships with the YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bridge_live.store import Passport, sha_for
from grok_build_bridge.parser import BridgeConfigError, load_yaml
from grok_build_bridge.safety import _run_static_scans


def passport_from_yaml(
    yaml_text: str,
    *,
    extra_code: str | None = None,
    seeded: bool = False,
) -> Passport:
    """Build a :class:`Passport` from the YAML payload of a bridge config.

    Args:
        yaml_text: Raw YAML bytes the user pasted or uploaded.
        extra_code: Optional source code to feed into the static safety
            scan. ``bridge.live`` is read-only and does not generate code,
            but bundled templates with ``source: local`` carry their
            entrypoint files alongside the YAML and we render those on
            the safety badge so the showcase looks complete.
        seeded: Marks the passport as part of the curated showcase
            (rendered on ``/showcase``). User-submitted passports leave
            this False.

    Raises:
        BridgeConfigError: If the YAML fails parsing or schema validation.
            The caller (FastAPI route) catches this and renders an error
            page with the rich error message.
    """
    # ``load_yaml`` writes a temp file to be schema-validated. Round-tripping
    # through a temp path keeps us on the canonical, well-tested code path
    # rather than re-implementing schema validation here.
    tmp = Path("/tmp") / f"bridge-live-{sha_for(yaml_text)}.yaml"
    tmp.write_text(yaml_text, encoding="utf-8")
    try:
        frozen_cfg = load_yaml(tmp)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:  # pragma: no cover — racey cleanup
            pass

    cfg: dict[str, Any] = _thaw(frozen_cfg)
    build = cfg.get("build", {}) or {}
    deploy = cfg.get("deploy", {}) or {}
    safety_cfg = cfg.get("safety", {}) or {}

    issues: list[str] = []
    if extra_code:
        language = str(build.get("language") or "python")
        issues = list(_run_static_scans(extra_code, language))

    return Passport(
        sha=sha_for(yaml_text),
        yaml_text=yaml_text,
        name=str(cfg.get("name", "")),
        description=str(cfg.get("description", "")),
        target=str(deploy.get("target", "")),
        model=str((cfg.get("agent") or {}).get("model", "")),
        source=str(build.get("source", "")),
        language=str(build.get("language", "")),
        entrypoint=str(build.get("entrypoint", "")),
        tools=[str(t) for t in (build.get("required_tools") or [])],
        schedule=(deploy.get("schedule") or None),
        safety_safe=not issues,
        safety_issues=issues,
        estimated_tokens=int(safety_cfg.get("max_tokens_per_run") or 0),
        seeded=seeded,
    )


# Re-exported so the FastAPI route can ``except`` it once.
__all__ = ["BridgeConfigError", "passport_from_yaml"]


def _thaw(value: Any) -> Any:
    """Recursively unfreeze a parser ``MappingProxyType`` tree.

    Mirrors the helper at :func:`grok_build_bridge.runtime._thaw` so the
    inspector can read fields with ``cfg.get(...)`` without leaking the
    proxy semantics out of this module.
    """
    from types import MappingProxyType

    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value
