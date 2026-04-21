"""Main bridge orchestrator.

Wires together the parser, builder, safety checker, and deployer, and exposes
a single :func:`bridge` coroutine that the CLI drives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grok_build_bridge.builder import BuildResult
from grok_build_bridge.parser import BridgeConfig
from grok_build_bridge.safety import SafetyReport


@dataclass(slots=True)
class BridgeResult:
    """End-to-end outcome of a single ``grok-build-bridge run`` invocation."""

    config: BridgeConfig
    build: BuildResult
    safety: SafetyReport
    deployed: bool
    deploy_target: str | None


async def bridge(
    config_path: str | Path,
    *,
    dry_run: bool = False,
) -> BridgeResult:
    """🚀 Parse, build, safety-check, and (optionally) deploy the agent."""
    raise NotImplementedError("filled in session 5")
