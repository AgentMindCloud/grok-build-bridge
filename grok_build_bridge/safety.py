"""Safety rails applied before any generated code reaches X.

Static checks (e.g. banned imports, path-traversal), plus model-in-the-loop
review that asks Grok to flag unsafe patterns before deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grok_build_bridge.builder import BuildResult


@dataclass(slots=True)
class SafetyFinding:
    """A single issue surfaced by the safety checker."""

    severity: str
    code: str
    message: str
    path: str | None = None
    line: int | None = None


@dataclass(slots=True)
class SafetyReport:
    """Outcome of running the safety suite against a :class:`BuildResult`."""

    passed: bool
    findings: list[SafetyFinding] = field(default_factory=list)


async def check(build_result: BuildResult) -> SafetyReport:
    """🛡️ Run the full safety pipeline and return a report."""
    raise NotImplementedError("filled in session 4")
