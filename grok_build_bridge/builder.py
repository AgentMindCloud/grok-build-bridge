"""Grok-prompt → code generator.

Takes a :class:`~grok_build_bridge.parser.BridgeConfig`, asks Grok (via
:class:`~grok_build_bridge.xai_client.XAIClient`) to synthesise the agent
codebase, writes files to a build directory, and returns a manifest of the
produced artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grok_build_bridge.parser import BridgeConfig
from grok_build_bridge.xai_client import XAIClient


@dataclass(slots=True)
class BuildArtifact:
    """A single file produced by the builder."""

    path: Path
    sha256: str
    bytes_written: int


@dataclass(slots=True)
class BuildResult:
    """Result of a full build run."""

    root: Path
    artifacts: list[BuildArtifact]


async def build(
    config: BridgeConfig,
    *,
    client: XAIClient,
    out_dir: Path,
) -> BuildResult:
    """⚡ Generate an agent codebase from ``config`` and write it under ``out_dir``."""
    raise NotImplementedError("filled in session 3")
