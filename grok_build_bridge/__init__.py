"""Grok Build Bridge — turn any Grok-generated codebase into a safely deployed X agent.

This package exposes the primary building blocks used by the ``grok-build-bridge``
CLI: YAML parsing, the xAI client wrapper, the code builder, safety rails,
the orchestration runtime, and the X deployment glue.
"""

from __future__ import annotations

__version__: str = "0.1.0"

__all__: list[str] = [
    "__version__",
    "builder",
    "cli",
    "deploy",
    "parser",
    "runtime",
    "safety",
    "xai_client",
]
