"""Filesystem-backed passport store.

A passport is a small JSON document keyed by an 8-char SHA-256 prefix
of the canonical YAML bytes. Storage lives at ``$BRIDGE_LIVE_HOME``
(default: ``./.passports``). Anything fancier (Postgres, Redis, S3) is
deferred until traffic justifies it — the MVP needs to ship in a day,
not a week.

The store is intentionally append-only: once a passport is written it
is never mutated. Re-submitting the same YAML returns the same SHA and
serves the existing passport as a side effect, which gives ``bridge.live``
deterministic, share-stable URLs for free.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_DEFAULT_HOME: Final[Path] = Path(".passports")
_SHA_PREFIX_LEN: Final[int] = 8


@dataclass(slots=True, frozen=True)
class Passport:
    """One stored passport.

    Fields are flat on purpose — the renderer wants to read them by name
    without a second hop into a nested ``meta`` dict.
    """

    sha: str
    yaml_text: str
    name: str
    description: str
    target: str
    model: str
    source: str
    language: str
    entrypoint: str
    tools: list[str]
    schedule: str | None
    safety_safe: bool
    safety_issues: list[str]
    estimated_tokens: int
    seeded: bool = False


def _store_root() -> Path:
    raw = os.environ.get("BRIDGE_LIVE_HOME")
    root = Path(raw) if raw else _DEFAULT_HOME
    root.mkdir(parents=True, exist_ok=True)
    return root


def sha_for(yaml_text: str) -> str:
    """Stable 8-char SHA prefix used as a passport id."""
    digest = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
    return digest[:_SHA_PREFIX_LEN]


def save(passport: Passport) -> Path:
    """Persist ``passport`` and return the on-disk path.

    Idempotent — re-submitting the same YAML is a no-op write because
    the SHA is content-derived.
    """
    path = _store_root() / f"{passport.sha}.json"
    payload: dict[str, Any] = {
        "sha": passport.sha,
        "yaml_text": passport.yaml_text,
        "name": passport.name,
        "description": passport.description,
        "target": passport.target,
        "model": passport.model,
        "source": passport.source,
        "language": passport.language,
        "entrypoint": passport.entrypoint,
        "tools": passport.tools,
        "schedule": passport.schedule,
        "safety_safe": passport.safety_safe,
        "safety_issues": passport.safety_issues,
        "estimated_tokens": passport.estimated_tokens,
        "seeded": passport.seeded,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load(sha: str) -> Passport | None:
    """Load a passport by its 8-char SHA, or ``None`` if not found."""
    path = _store_root() / f"{sha}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _from_dict(data)


def list_seeded() -> list[Passport]:
    """Return every persisted passport flagged as ``seeded=True``.

    The showcase page iterates over these to render the gallery; user-
    submitted passports are excluded so a stranger's YAML cannot
    accidentally land on the public homepage.
    """
    root = _store_root()
    out: list[Passport] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("seeded"):
            out.append(_from_dict(data))
    return out


def _from_dict(data: dict[str, Any]) -> Passport:
    return Passport(
        sha=str(data["sha"]),
        yaml_text=str(data["yaml_text"]),
        name=str(data["name"]),
        description=str(data.get("description", "")),
        target=str(data.get("target", "")),
        model=str(data.get("model", "")),
        source=str(data.get("source", "")),
        language=str(data.get("language", "")),
        entrypoint=str(data.get("entrypoint", "")),
        tools=[str(t) for t in (data.get("tools") or [])],
        schedule=(data.get("schedule") or None),
        safety_safe=bool(data.get("safety_safe", True)),
        safety_issues=[str(i) for i in (data.get("safety_issues") or [])],
        estimated_tokens=int(data.get("estimated_tokens", 0)),
        seeded=bool(data.get("seeded", False)),
    )
