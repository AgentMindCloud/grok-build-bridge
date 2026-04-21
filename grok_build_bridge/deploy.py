"""Deploy glue — bridges a built agent into the running ``grok-install`` ecosystem.

Prefers the real ``deploy_to_x`` shipped by ``grok_install.runtime``. When
that package is not importable (e.g. local dev without the ecosystem
cloned), a dry-run stub writes the payload to ``./generated/deploy_payload.json``
so the rest of the bridge can still exercise its code paths.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

logger: Final[logging.Logger] = logging.getLogger(__name__)

DeployFn = Callable[[dict[str, Any]], Any]

_DRY_RUN_PAYLOAD_PATH: Final[Path] = Path("generated") / "deploy_payload.json"


def _dry_run_stub(payload: dict[str, Any]) -> dict[str, Any]:
    """Fallback used when ``grok_install`` is not importable."""
    print("⚠️  grok_install not installed — dry-run only")
    _DRY_RUN_PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DRY_RUN_PAYLOAD_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    logger.info("dry-run payload written to %s", _DRY_RUN_PAYLOAD_PATH)
    return {"dry_run": True, "path": str(_DRY_RUN_PAYLOAD_PATH)}


try:
    from grok_install.runtime import deploy_to_x as _deploy_to_x  # type: ignore[import-not-found]

    deploy_to_x: DeployFn = _deploy_to_x
    logger.info("deploy path: grok_install.runtime.deploy_to_x")
except ImportError:
    deploy_to_x = _dry_run_stub
    logger.info("deploy path: local dry-run stub (grok_install not installed)")


def deploy(payload: dict[str, Any]) -> Any:
    """🎤 Deploy ``payload`` to X via the best available backend."""
    raise NotImplementedError("filled in session 5")
