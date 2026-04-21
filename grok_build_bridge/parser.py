"""YAML parser and schema validator for bridge configuration files.

Loads a ``bridge.yaml`` file, validates it against
``grok_build_bridge/schema/bridge.schema.json``, and returns a typed
configuration object for downstream consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BridgeConfig:
    """Typed representation of a validated ``bridge.yaml`` document."""

    name: str
    prompt: str
    model: str | None
    safety: dict[str, Any]
    deploy: dict[str, Any]
    raw: dict[str, Any]


def load(path: str | Path) -> BridgeConfig:
    """Load and validate a bridge YAML file into a :class:`BridgeConfig`."""
    raise NotImplementedError("filled in session 2")


def validate(document: dict[str, Any]) -> None:
    """Validate a parsed YAML mapping against the bundled JSON schema."""
    raise NotImplementedError("filled in session 2")
