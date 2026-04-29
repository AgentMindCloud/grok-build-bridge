"""Grok Build Bridge — turn any Grok-generated codebase into a safely deployed X agent.

The package exposes two entry surfaces:

* The ``grok-build-bridge`` CLI (see :mod:`grok_build_bridge.cli`).
* A small Python SDK for driving the same pipeline from notebooks,
  CI scripts, or another framework — re-exported below so a caller
  can write::

      from grok_build_bridge import run_bridge

      result = run_bridge("bridge.yaml", dry_run=True)

  instead of digging into the ``runtime`` submodule. The CLI itself
  imports through this exact public surface, so the two paths can never
  drift.
"""

from __future__ import annotations

__version__: str = "0.1.0"

# Re-exports — the SDK surface. Keep this list intentionally small;
# anything not listed is private and may change between minor versions.
from grok_build_bridge.parser import BridgeConfigError, load_yaml
from grok_build_bridge.runtime import BridgePhaseError, BridgeResult, run_bridge
from grok_build_bridge.safety import BridgeSafetyError, SafetyReport
from grok_build_bridge.xai_client import BridgeRuntimeError, XAIClient

__all__: list[str] = [
    "__version__",
    # SDK — drive the bridge from Python.
    "run_bridge",
    "load_yaml",
    "BridgeResult",
    "SafetyReport",
    "XAIClient",
    # Exception hierarchy.
    "BridgeConfigError",
    "BridgePhaseError",
    "BridgeRuntimeError",
    "BridgeSafetyError",
    # Submodules (kept for back-compat; new code should use the SDK above).
    "builder",
    "cli",
    "deploy",
    "parser",
    "runtime",
    "safety",
    "xai_client",
]
