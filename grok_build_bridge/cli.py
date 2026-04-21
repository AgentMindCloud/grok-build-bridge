"""Typer-based command-line interface for ``grok-build-bridge``.

The CLI is the single entrypoint exposed by the package. It wires the YAML
parser, the builder, the safety checker, and the deploy glue into subcommands
such as ``run``, ``build``, and ``deploy``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from grok_build_bridge import __version__

app: typer.Typer = typer.Typer(
    name="grok-build-bridge",
    help="🎯 Turn any Grok-generated codebase into a safely deployed X agent.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the grok-build-bridge version and exit.",
        is_eager=True,
    ),
) -> None:
    """🎯 Grok Build Bridge — one YAML file, one command, one deployed X agent."""
    if version:
        typer.echo(f"grok-build-bridge {__version__}")
        raise typer.Exit(code=0)


@app.command("run")
def run(
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
        help="🛡️ Build and validate without deploying to X.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Proceed with deploy even if the safety scan reports issues.",
    ),
) -> None:
    """🚀 Run the full build → safety → deploy bridge for a YAML config."""
    from grok_build_bridge.runtime import (
        BridgePhaseError,
        _report_error,
        run_bridge,
    )

    try:
        result = run_bridge(config, dry_run=dry_run, force=force)
    except BridgePhaseError as exc:
        _report_error(exc)
        raise typer.Exit(code=1) from exc
    if not result.success:
        raise typer.Exit(code=1)


@app.command("build")
def build(
    config: Path = typer.Argument(..., help="Path to the bridge YAML file."),
) -> None:
    """⚡ Generate the agent codebase from a Grok prompt, without deploying."""
    raise NotImplementedError("filled in session 3")


@app.command("deploy")
def deploy(
    config: Path = typer.Argument(..., help="Path to the bridge YAML file."),
) -> None:
    """🎤 Deploy an already-built agent to X."""
    raise NotImplementedError("filled in session 4")


def main() -> None:
    """Console-script entrypoint registered in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
