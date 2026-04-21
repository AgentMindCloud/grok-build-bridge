"""Shared Rich console and logging helpers used across the package.

Every module that needs to print to the user imports from here rather than
instantiating its own :class:`rich.console.Console`. A single shared console
guarantees:

* No interleaved output when multiple modules print concurrently.
* One central place to change styling, width, or the output stream (stderr
  vs. stdout) without touching every callsite.

The private underscore prefix signals that this is an internal helper — it
is not part of the public API exposed by ``grok_build_bridge.__init__``.
"""

from __future__ import annotations

from typing import Final

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

# Human output goes to stderr so that any future subcommand that prints
# machine-readable results to stdout (JSON manifests, build artefact paths,
# etc.) does not get mixed with status chatter.
console: Final[Console] = Console(stderr=True, highlight=False, soft_wrap=True)


def info(message: str) -> None:
    """Print an informational line in the shared console style."""
    console.print(Text("ℹ  ", style="cyan bold") + Text(message))


def warn(message: str) -> None:
    """Print a warning line — used by retry hooks and safety nags."""
    console.print(Text(message, style="yellow"))


def error(message: str) -> None:
    """Print an error line. Does NOT raise; callers decide on control flow."""
    console.print(Text(message, style="bold red"))


def section(title: str) -> None:
    """Print a styled divider titled ``title`` to group log sections."""
    console.print(Rule(title=title, style="magenta"))
