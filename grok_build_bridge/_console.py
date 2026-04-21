"""Shared Rich console, brand theme, and progress helpers.

Every module that needs to print goes through this module so the
brand palette lives in exactly one place and color choices stay
out of inline call sites. The spirit: no ``style="#00ffff"`` anywhere
in the codebase — always a ``brand.*`` name from the theme below.

Tokens:

* ``brand.primary``   — the cyan headline / progress spinner colour
* ``brand.secondary`` — the blue accent used alongside primary
* ``brand.success``   — the green for success panels and OK ticks
* ``brand.warn``      — the yellow for warnings / retry notices
* ``brand.error``     — the red for error panels and blocked phases
* ``brand.muted``     — the dim text used for timestamps and notes
* ``brand.accent``    — the magenta used for section dividers

Gradient series used for the banner stays here too
(:data:`BANNER_GRADIENT`) so any cosmetic tweaks land in one file.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme

_BRAND_THEME: Final[Theme] = Theme(
    {
        "brand.primary": "bold cyan",
        "brand.secondary": "blue",
        "brand.success": "bold green",
        "brand.warn": "yellow",
        "brand.error": "bold red",
        "brand.muted": "dim",
        "brand.accent": "magenta",
    }
)

# Cyan → blue gradient used one-line-at-a-time by :mod:`_banner`. These are
# 256-colour palette entries so the banner still renders on terminals that
# do not support truecolour. Keeping them here (not in ``_banner.py``) means
# a future rebrand changes one list, not two files.
BANNER_GRADIENT: Final[tuple[str, ...]] = (
    "bold color(51)",
    "bold color(45)",
    "bold color(39)",
    "bold color(33)",
    "bold color(27)",
    "bold color(21)",
)

# Human output goes to stderr so that any future subcommand that prints
# machine-readable results to stdout (JSON manifests, build artefact paths,
# etc.) does not get mixed with status chatter.
console: Final[Console] = Console(
    stderr=True,
    highlight=False,
    soft_wrap=True,
    theme=_BRAND_THEME,
)


def info(message: str) -> None:
    """Print an informational line in the shared console style."""
    console.print(Text("ℹ  ", style="brand.primary") + Text(message))


def warn(message: str) -> None:
    """Print a warning line — used by retry hooks and safety nags."""
    console.print(Text(message, style="brand.warn"))


def error(message: str) -> None:
    """Print an error line. Does NOT raise; callers decide on control flow."""
    console.print(Text(message, style="brand.error"))


def section(title: str) -> None:
    """Print a styled divider titled ``title`` to group log sections."""
    console.print(Rule(title=title, style="brand.accent"))


@contextmanager
def phase_progress(description: str) -> Iterator[tuple[Progress, int]]:
    """Rich progress context for a single long-running phase.

    Yields ``(progress, task_id)`` so callers can bump the token counter as
    work completes::

        with phase_progress("🎯  generating") as (prog, task):
            # ... do work ...
            prog.update(task, tokens=123)

    Transient so the finished line disappears once the phase ends, leaving
    the section rule as the permanent record.
    """
    progress = Progress(
        SpinnerColumn(style="brand.primary"),
        TextColumn("[brand.primary]{task.description}"),
        TimeElapsedColumn(),
        TextColumn("[brand.muted]{task.fields[tokens]} tok[/]"),
        console=console,
        transient=True,
    )
    with progress:
        task_id = progress.add_task(description, total=None, tokens=0)
        yield progress, task_id
