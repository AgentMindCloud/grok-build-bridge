"""Typer + Rich command-line interface for ``grok-build-bridge``.

Five user-facing commands:

* ``run``       — build, safety-scan, and deploy from one YAML.
* ``validate``  — parser-only pretty-print of the resolved config.
* ``templates`` — list bundled templates with description and required env.
* ``init``      — copy a bundled template to the user's working directory.
* ``version``   — show grok-build-bridge / xai-sdk / python versions.

Every failure path renders a red Rich panel with a "What to try next"
bullet list and exits with a typed code:

* ``2`` — :class:`BridgeConfigError` (YAML / schema issues).
* ``3`` — :class:`BridgeRuntimeError` (build / deploy infrastructure).
* ``4`` — :class:`BridgeSafetyError` (safety audit blocked the run).
"""

from __future__ import annotations

import importlib.resources as resources
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import typer
import yaml
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from grok_build_bridge import __version__
from grok_build_bridge._banner import print_banner
from grok_build_bridge._console import console
from grok_build_bridge.parser import BridgeConfigError, load_yaml
from grok_build_bridge.xai_client import BridgeRuntimeError

# ---------------------------------------------------------------------------
# Exit codes (task-defined)
# ---------------------------------------------------------------------------

_EXIT_CONFIG: Final[int] = 2
_EXIT_RUNTIME: Final[int] = 3
_EXIT_SAFETY: Final[int] = 4


# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

app: typer.Typer = typer.Typer(
    name="grok-build-bridge",
    help=(
        "🎯 Grok Build Bridge — one YAML, one command, one deployed X agent.\n\n"
        "Turn any Grok-generated codebase into a safely deployed X agent "
        "via one YAML file and one CLI command."
    ),
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version_flag: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the grok-build-bridge version and exit.",
        is_eager=True,
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable ANSI colors (also settable via NO_COLOR env var).",
        is_eager=True,
    ),
) -> None:
    """Global options for grok-build-bridge."""
    if no_color:
        os.environ["NO_COLOR"] = "1"
        console.no_color = True
    if version_flag:
        _print_version_panel()
        raise typer.Exit(code=0)
    # ``invoke_without_command=True`` lets ``--version`` work without a
    # subcommand; when neither is given, fall back to the help screen.
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def _render_error_panel(title: str, exc: BaseException, hints: Sequence[str]) -> None:
    """Render a red Rich panel with message + 'What to try next' bullets."""
    body = Text()
    body.append(f"{type(exc).__name__}: ", style="brand.error")
    body.append(str(exc))
    body.append("\n\n")
    body.append("What to try next:\n", style="brand.primary")
    for hint in hints:
        body.append("  • ", style="brand.muted")
        body.append(hint + "\n")
    console.print(
        Panel(body, title=f"[brand.error]{title}[/]", border_style="brand.error")
    )


def _hints_for(exc: BaseException) -> list[str]:
    """Best-effort next-step hints for an error."""
    hints: list[str] = []
    suggestion = getattr(exc, "suggestion", None)
    if suggestion:
        hints.append(suggestion)
    if isinstance(exc, BridgeConfigError):
        hints.append("Run `grok-build-bridge validate <file.yaml>` to inspect defaults.")
    hints.append(
        "Run with --verbose for a full traceback, or see the docs at "
        "https://github.com/AgentMindCloud/grok-build-bridge."
    )
    return hints


def _handle_and_exit(exc: BaseException, *, verbose: bool = False) -> None:
    """Render a branded error panel and exit with the correct typed code."""
    # Unwrap BridgePhaseError so the panel reflects the actual failure mode.
    real: BaseException = exc
    from grok_build_bridge.runtime import BridgePhaseError  # local import: avoids cycle

    while isinstance(real, BridgePhaseError):
        real = real.cause or real

    if isinstance(real, BridgeConfigError):
        title = "📄 Config Error"
        code = _EXIT_CONFIG
    else:
        # BridgeSafetyError is a subclass of BridgeRuntimeError, so check it first.
        from grok_build_bridge.safety import BridgeSafetyError

        if isinstance(real, BridgeSafetyError):
            title = "🛡️  Safety Error"
            code = _EXIT_SAFETY
        elif isinstance(real, BridgeRuntimeError):
            title = "🚫 Runtime Error"
            code = _EXIT_RUNTIME
        else:
            title = "🚫 Unexpected Error"
            code = _EXIT_RUNTIME

    _render_error_panel(title, real, _hints_for(real))
    if verbose:
        console.print_exception(show_locals=False)
    raise typer.Exit(code=code)


# ---------------------------------------------------------------------------
# `run` command
# ---------------------------------------------------------------------------


@app.command("run")
def run_cmd(
    config: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the bridge YAML file.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="🛡️  Build and validate without deploying.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Proceed even if the safety scan reports issues.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print full tracebacks on failure.",
    ),
) -> None:
    """🚀 Run the full build → safety → deploy bridge for a YAML config."""
    print_banner(console)
    try:
        from grok_build_bridge.runtime import run_bridge

        result = run_bridge(config, dry_run=dry_run, force=force)
    except (BridgeConfigError, BridgeRuntimeError) as exc:
        _handle_and_exit(exc, verbose=verbose)
    if not result.success:
        raise typer.Exit(code=_EXIT_RUNTIME)


# ---------------------------------------------------------------------------
# `validate` command
# ---------------------------------------------------------------------------


@app.command("validate")
def validate_cmd(
    config: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the bridge YAML file.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Full tracebacks."),
) -> None:
    """📄  Parse, validate, and pretty-print a bridge YAML file."""
    try:
        cfg = load_yaml(config)
    except BridgeConfigError as exc:
        _handle_and_exit(exc, verbose=verbose)
    tree = _config_to_tree(cfg, label=f"📄  {config}")
    console.print(tree)
    console.print(
        Panel(
            Text("✅ valid", style="brand.success"),
            border_style="brand.success",
        )
    )


def _config_to_tree(value: Any, *, label: str) -> Tree:
    """Recursively render a parsed config mapping as a Rich :class:`Tree`."""
    root = Tree(f"[brand.primary]{label}[/]")
    _attach_children(root, value)
    return root


def _attach_children(node: Tree, value: Any) -> None:
    if isinstance(value, dict) or _is_mapping_proxy(value):
        for key, child in value.items():
            if isinstance(child, dict) or _is_mapping_proxy(child):
                sub = node.add(f"[brand.secondary]{key}[/]")
                _attach_children(sub, child)
            elif isinstance(child, (list, tuple)):
                sub = node.add(f"[brand.secondary]{key}[/]")
                for item in child:
                    sub.add(Text(str(item), style="brand.muted"))
            else:
                node.add(
                    Text.assemble(
                        (f"{key}: ", "brand.secondary"),
                        (str(child), "brand.muted"),
                    )
                )


def _is_mapping_proxy(value: Any) -> bool:
    from types import MappingProxyType

    return isinstance(value, MappingProxyType)


# ---------------------------------------------------------------------------
# `templates` command
# ---------------------------------------------------------------------------


@app.command("templates")
def templates_cmd() -> None:
    """📚  List bundled templates available to ``init``."""
    entries = list(_discover_templates())
    if not entries:
        console.print(
            Panel(
                Text("No bundled templates found.", style="brand.warn"),
                border_style="brand.warn",
            )
        )
        return

    table = Table(
        title="[brand.primary]Bundled templates[/]",
        border_style="brand.secondary",
    )
    table.add_column("name", style="brand.primary", no_wrap=True)
    table.add_column("description")
    table.add_column("required env", style="brand.muted")
    for entry in entries:
        env = ", ".join(entry.get("required_env") or []) or "—"
        table.add_row(
            str(entry.get("name", "")),
            str(entry.get("description", "")),
            env,
        )
    console.print(table)


def _discover_templates() -> Iterable[dict[str, Any]]:
    """Yield parsed ``template.yaml`` manifests from the bundled templates."""
    root = resources.files("grok_build_bridge.templates")
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        manifest = entry / "template.yaml"
        if not manifest.is_file():
            continue
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            data.setdefault("name", entry.name)
            yield data


# ---------------------------------------------------------------------------
# `init` command
# ---------------------------------------------------------------------------


@app.command("init")
def init_cmd(
    template_name: str = typer.Argument(..., help="Name of the bundled template."),
    out: Path = typer.Option(
        Path.cwd(),
        "--out",
        "-o",
        help="Destination directory (default: current working directory).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing files without prompting.",
    ),
) -> None:
    """⚡  Copy a bundled template to ``--out`` (or the current directory)."""
    template_root = resources.files("grok_build_bridge.templates") / template_name
    if not template_root.is_dir():
        _render_error_panel(
            "📚 Template not found",
            BridgeRuntimeError(f"no bundled template named {template_name!r}"),
            [
                "Run `grok-build-bridge templates` to list available templates.",
            ],
        )
        raise typer.Exit(code=_EXIT_CONFIG)

    out.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    for src in _walk_template(template_root):
        rel = src.relative_to(template_root)
        if rel.name == "template.yaml":
            continue
        dst = out / rel
        if dst.exists() and not force:
            if not typer.confirm(
                f"{dst} already exists. Overwrite?",
                default=False,
            ):
                console.print(Text(f"skipped {dst}", style="brand.muted"))
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)

    body = Text()
    body.append("Template ")
    body.append(template_name, style="brand.primary")
    body.append(" copied.\n\n")
    for path in copied:
        body.append("  + ", style="brand.success")
        body.append(str(path) + "\n")
    body.append("\nNext: ", style="brand.primary")
    body.append(
        "edit the bridge.yaml, then run `grok-build-bridge run bridge.yaml --dry-run`."
    )
    console.print(
        Panel(
            body,
            title="[brand.success]⚡  init complete[/]",
            border_style="brand.success",
        )
    )


def _walk_template(root: Any) -> Iterable[Path]:
    """Yield every file under a template resource directory as real Paths."""
    # resources.files returns Traversable; we materialise to Path via
    # as_file for the duration of iteration.
    with resources.as_file(root) as root_path:
        for path in Path(root_path).rglob("*"):
            if path.is_file():
                yield path


# ---------------------------------------------------------------------------
# `version` command
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """ℹ️  Show grok-build-bridge / xai-sdk / python versions."""
    _print_version_panel()


def _print_version_panel() -> None:
    try:
        import xai_sdk  # noqa: WPS433

        xai_version = getattr(xai_sdk, "__version__", "unknown")
    except ImportError:  # pragma: no cover
        xai_version = "not installed"

    body = Text()
    body.append("grok-build-bridge  ", style="brand.primary")
    body.append(__version__ + "\n", style="brand.muted")
    body.append("xai-sdk            ", style="brand.primary")
    body.append(xai_version + "\n", style="brand.muted")
    body.append("python             ", style="brand.primary")
    body.append(sys.version.split()[0], style="brand.muted")
    console.print(
        Panel(
            body,
            title="[brand.primary]🎯  grok-build-bridge[/]",
            border_style="brand.secondary",
        )
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script entrypoint registered in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
