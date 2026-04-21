"""Branded ASCII banner printed at the top of ``grok-build-bridge run``.

Six lines of block-lettered "GROK BUILD BRIDGE" rendered with a
per-line cyan→blue gradient. The gradient palette lives in
:mod:`grok_build_bridge._console` (``BANNER_GRADIENT``) so all brand
colour choices stay in one module.
"""

from __future__ import annotations

from typing import Final

from rich.console import Console
from rich.text import Text

from grok_build_bridge._console import BANNER_GRADIENT

_BANNER_LINES: Final[tuple[str, ...]] = (
    " ██████╗ ██████╗  ██████╗ ██╗  ██╗    ██████╗ ██╗   ██╗██╗██╗     ██████╗     ██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗",
    "██╔════╝ ██╔══██╗██╔═══██╗██║ ██╔╝    ██╔══██╗██║   ██║██║██║     ██╔══██╗    ██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝",
    "██║  ███╗██████╔╝██║   ██║█████╔╝     ██████╔╝██║   ██║██║██║     ██║  ██║    ██████╔╝██████╔╝██║██║  ██║██║  ███╗█████╗  ",
    "██║   ██║██╔══██╗██║   ██║██╔═██╗     ██╔══██╗██║   ██║██║██║     ██║  ██║    ██╔══██╗██╔══██╗██║██║  ██║██║   ██║██╔══╝  ",
    "╚██████╔╝██║  ██║╚██████╔╝██║  ██╗    ██████╔╝╚██████╔╝██║███████╗██████╔╝    ██████╔╝██║  ██║██║██████╔╝╚██████╔╝███████╗",
    " ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝    ╚═════╝  ╚═════╝ ╚═╝╚══════╝╚═════╝     ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚══════╝",
)

_TAGLINE: Final[str] = "One YAML. Grok builds it. Safely on X."


def print_banner(console: Console) -> None:
    """Render the gradient banner + tagline to ``console``.

    Kept purely cosmetic — callers should tolerate terminals that do not
    support the 256-colour palette; Rich transparently downgrades.
    """
    for line, style in zip(_BANNER_LINES, BANNER_GRADIENT, strict=True):
        console.print(Text(line, style=style))
    console.print(Text(_TAGLINE, style="brand.secondary"))
    console.print()
