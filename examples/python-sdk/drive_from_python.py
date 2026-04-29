"""Drive grok-build-bridge from a Python script (or a Jupyter notebook).

Run this against any ``bridge.yaml`` to exercise the same pipeline the
CLI uses, programmatically. Useful for:

* CI runners that want a typed result rather than parsing CLI output.
* Notebooks where you want to inspect ``result.safety_report.issues``
  inline.
* Composing Bridge inside another framework (e.g. an Orchestra debate
  that decides whether to call ``run_bridge`` at all).

Usage:

    python examples/python-sdk/drive_from_python.py path/to/bridge.yaml

No XAI key is required for this script — every example below uses
``dry_run=True`` and skips any path that needs a Grok call.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The SDK surface is re-exported at the package root so callers don't
# have to know which submodule a name lives in.
from grok_build_bridge import (
    BridgeConfigError,
    BridgePhaseError,
    BridgeResult,
    run_bridge,
)


def main(yaml_path: Path) -> int:
    try:
        result: BridgeResult = run_bridge(yaml_path, dry_run=True)
    except BridgeConfigError as exc:
        print(f"❌ config error: {exc}", file=sys.stderr)
        return 2
    except BridgePhaseError as exc:
        # The phase tag tells you exactly where the pipeline failed.
        print(f"❌ phase {exc.phase!r} failed: {exc.cause}", file=sys.stderr)
        return 3

    # Success — every interesting field lives on the BridgeResult dataclass.
    print(f"✅ {yaml_path}")
    print(f"   generated:  {result.generated_path}")
    if result.safety_report is not None:
        verdict = "safe" if result.safety_report.safe else "BLOCKED"
        print(
            f"   safety:     {verdict} "
            f"({len(result.safety_report.issues)} issue(s), "
            f"score={result.safety_report.score:.2f})"
        )
    print(f"   target:     {result.deploy_target}")
    print(f"   tokens:     {result.total_tokens}")
    print(f"   duration:   {result.duration_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
