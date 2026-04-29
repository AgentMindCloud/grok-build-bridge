"""Typer + Rich command-line interface for ``grok-build-bridge``.

Ten user-facing commands:

* ``run``       — build, safety-scan, and deploy from one YAML.
* ``validate``  — parser-only pretty-print of the resolved config.
* ``templates`` — list bundled templates with description and required env.
* ``init``      — copy a bundled template to the user's working directory.
* ``link``      — wire two bridge YAMLs into a publisher / Lucas-veto pair.
* ``fork``      — reconstruct a bridge.yaml from a published zip or passport URL.
* ``publish``   — package a built agent for the future grokagents.dev marketplace.
* ``dev``       — hot-reload watcher; re-runs phases 1-3 on every save.
* ``doctor``    — probe the local environment for everything Bridge needs.
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
    console.print(Panel(body, title=f"[brand.error]{title}[/]", border_style="brand.error"))


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
    allow_stub: bool = typer.Option(
        False,
        "--allow-stub",
        help=(
            "Permit fallback stubs when an optional dependency is missing: "
            "direct Grok generation for `grok-build-cli` sources, and the "
            "local payload writer for `deploy.target: x`. Off by default."
        ),
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

        result = run_bridge(config, dry_run=dry_run, force=force, allow_stub=allow_stub)
    except (BridgeConfigError, BridgeRuntimeError) as exc:
        _handle_and_exit(exc, verbose=verbose)
    if not result.success:
        raise typer.Exit(code=_EXIT_RUNTIME)


# ---------------------------------------------------------------------------
# `dev` command — hot-reload watcher
# ---------------------------------------------------------------------------


# Directories the watcher must skip. Polling them is wasteful, and ``generated/``
# specifically would loop forever because every dry-run rewrites the manifest.
_WATCH_IGNORE: Final[frozenset[str]] = frozenset(
    {
        "generated",
        ".git",
        ".venv",
        "venv",
        ".passports",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
    }
)


@app.command("dev")
def dev_cmd(
    config: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the bridge YAML file.",
    ),
    interval: float = typer.Option(
        0.5,
        "--interval",
        help="Polling interval in seconds. Lower = snappier reload, more CPU.",
        min=0.1,
        max=10.0,
    ),
    allow_stub: bool = typer.Option(
        False,
        "--allow-stub",
        help="Permit fallback stubs when an optional dependency is missing.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Print full tracebacks on failure."
    ),
) -> None:
    """🔁 Watch a bridge YAML and re-run phases 1-3 on every save.

    Iteration loop for working on a bridge.yaml without retyping
    ``run --dry-run`` every time. The watcher polls the YAML and any
    sibling source files, ignoring ``generated/``, ``.passports/``,
    ``.git/``, ``__pycache__``, and the usual virtualenv directories.
    Press Ctrl+C to exit.
    """
    import time

    from grok_build_bridge.runtime import BridgePhaseError, run_bridge

    if not config.is_file():
        _render_error_panel(
            "📄 Config Error",
            BridgeConfigError(f"bridge YAML not found: {config}"),
            ["Pass an existing path: `grok-build-bridge dev path/to/bridge.yaml`."],
        )
        raise typer.Exit(code=_EXIT_CONFIG)

    print_banner(console)
    console.print(
        Panel(
            Text.from_markup(
                f"[brand.primary]🔁 dev[/]  watching [brand.muted]{config}[/]"
                f" — interval [brand.muted]{interval:.2f}s[/] · [brand.muted]Ctrl+C[/] to exit"
            ),
            border_style="brand.secondary",
        )
    )

    last_mtimes: dict[Path, float] = {}
    iteration = 0
    try:
        while True:
            current = _watch_mtimes(_watch_paths(config))
            if iteration == 0 or current != last_mtimes:
                last_mtimes = current
                iteration += 1
                console.rule(f"[brand.muted]run #{iteration}  ·  {time.strftime('%H:%M:%S')}[/]")
                try:
                    run_bridge(config, dry_run=True, allow_stub=allow_stub)
                except BridgeConfigError as exc:
                    _render_error_panel("📄 Config Error", exc, _hints_for(exc))
                except BridgePhaseError as exc:
                    _render_error_panel(
                        "🚫 Phase Error", exc.cause or exc, _hints_for(exc.cause or exc)
                    )
                    if verbose:
                        console.print_exception(show_locals=False)
                except BridgeRuntimeError as exc:
                    _render_error_panel("🚫 Runtime Error", exc, _hints_for(exc))
                    if verbose:
                        console.print_exception(show_locals=False)
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print(Text("👋  bye", style="brand.muted"))
        raise typer.Exit(code=0) from None


def _watch_paths(config: Path) -> set[Path]:
    """Compute the set of files the dev watcher should poll.

    Walks the YAML's parent directory, skipping the well-known
    machine-generated and virtualenv directories listed in
    :data:`_WATCH_IGNORE`. Returns the YAML path itself even when the
    parent walk finds nothing, so a freshly-created bridge in an
    otherwise-empty cwd still gets reloaded on save.
    """
    paths: set[Path] = {config}
    root = config.parent
    if not root.exists():
        return paths
    for entry in root.rglob("*"):
        if any(part in _WATCH_IGNORE for part in entry.parts):
            continue
        if entry.is_file():
            paths.add(entry)
    return paths


def _watch_mtimes(paths: Iterable[Path]) -> dict[Path, float]:
    """Snapshot ``path → mtime`` for every existing file in ``paths``.

    Files that disappear between calls drop out of the dict, and that
    counts as a change in the next comparison — saving + atomic-renaming
    a YAML (the editor pattern most Python tools use) flips the mtime.
    """
    out: dict[Path, float] = {}
    for p in paths:
        try:
            out[p] = p.stat().st_mtime
        except FileNotFoundError:
            continue
    return out


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
    table.add_column("est. tokens", style="brand.muted", justify="right")
    table.add_column("categories", style="brand.muted")
    for entry in entries:
        env = ", ".join(entry.get("required_env") or []) or "—"
        cats = ", ".join(entry.get("categories") or []) or "—"
        tokens = entry.get("estimated_tokens")
        tokens_str = f"{tokens:,}" if isinstance(tokens, int) else "—"
        table.add_row(
            str(entry.get("name", "")),
            str(entry.get("description", "")),
            env,
            tokens_str,
            cats,
        )
    console.print(table)


def _discover_templates() -> Iterable[dict[str, Any]]:
    """Yield template entries from the bundled ``INDEX.yaml`` registry."""
    return _load_template_index()


def _load_template_index() -> list[dict[str, Any]]:
    """Parse ``grok_build_bridge/templates/INDEX.yaml`` into an entry list.

    Returns an empty list if the registry is missing or unreadable — the
    CLI degrades to "no templates" rather than crashing on a packaging bug.
    """
    root = resources.files("grok_build_bridge.templates")
    index_path = root / "INDEX.yaml"
    if not index_path.is_file():
        return []
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw_entries = data.get("templates") or []
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict[str, Any]] = []
    for entry in raw_entries:
        if isinstance(entry, dict) and entry.get("slug"):
            entries.append(entry)
    return entries


def _lookup_template(slug: str) -> dict[str, Any] | None:
    """Return the INDEX.yaml entry whose ``slug`` matches, or ``None``."""
    for entry in _load_template_index():
        if entry.get("slug") == slug:
            return entry
    return None


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
    entry = _lookup_template(template_name)
    if entry is None:
        _render_error_panel(
            "📚 Template not found",
            BridgeRuntimeError(f"no bundled template named {template_name!r}"),
            [
                "Run `grok-build-bridge templates` to list available templates.",
            ],
        )
        raise typer.Exit(code=_EXIT_CONFIG)

    file_specs = entry.get("files") or []
    if not isinstance(file_specs, list) or not file_specs:
        _render_error_panel(
            "📚 Template is empty",
            BridgeRuntimeError(f"template {template_name!r} has no files declared in INDEX.yaml"),
            ["Open INDEX.yaml in the templates dir and add a files: list."],
        )
        raise typer.Exit(code=_EXIT_CONFIG)

    templates_root = resources.files("grok_build_bridge.templates")
    out.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    for spec in file_specs:
        src_rel = spec.get("src") if isinstance(spec, dict) else None
        dst_rel = spec.get("dst") if isinstance(spec, dict) else None
        if not src_rel or not dst_rel:
            continue
        src_res = templates_root / src_rel
        dst = out / dst_rel
        if not src_res.is_file():
            console.print(Text(f"skipped (missing source): {src_rel}", style="brand.warn"))
            continue
        if dst.exists() and not force:
            if not typer.confirm(
                f"{dst} already exists. Overwrite?",
                default=False,
            ):
                console.print(Text(f"skipped {dst}", style="brand.muted"))
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with resources.as_file(src_res) as src_path:
            shutil.copy2(src_path, dst)
        copied.append(dst)

    body = Text()
    body.append("Template ")
    body.append(template_name, style="brand.primary")
    body.append(" copied.\n\n")
    for path in copied:
        body.append("  + ", style="brand.success")
        body.append(str(path) + "\n")
    body.append("\nNext: ", style="brand.primary")
    body.append("edit the bridge.yaml, then run `grok-build-bridge run bridge.yaml --dry-run`.")
    console.print(
        Panel(
            body,
            title="[brand.success]⚡  init complete[/]",
            border_style="brand.success",
        )
    )


# ---------------------------------------------------------------------------
# `link` command — wire two bridge YAMLs into a publish/veto pair
# ---------------------------------------------------------------------------


@app.command("link")
def link_cmd(
    publisher: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Bridge YAML for the agent that publishes (will be vetoed).",
    ),
    veto: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Bridge YAML for the agent that holds the veto.",
    ),
    out_dir: Path = typer.Option(
        Path.cwd(),
        "--out",
        "-o",
        help="Output directory (default: cwd). Linked files are written here.",
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help="Modify the publisher YAML in place instead of writing a `.linked.yaml` copy.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing files without prompting.",
    ),
) -> None:
    """🔗  Wire two bridge YAMLs together — publisher gets vetoed by veto agent.

    Sets ``safety.lucas_veto_enabled: true`` on the publisher YAML and
    writes an ``orchestra-spec.yaml`` sidecar that
    [grok-agent-orchestra](https://github.com/AgentMindCloud/grok-agent-orchestra)
    consumes to run the veto gate before each publish. The two source
    YAMLs themselves are unchanged unless ``--in-place`` is passed.
    """
    if publisher.resolve() == veto.resolve():
        _render_error_panel(
            "🔗 Link Error",
            BridgeRuntimeError(
                "publisher and veto agents cannot be the same YAML",
                suggestion="Pick a second bridge YAML to act as the veto gate.",
            ),
            ["Run `grok-build-bridge templates` to see candidates."],
        )
        raise typer.Exit(code=_EXIT_CONFIG)

    try:
        publisher_cfg = load_yaml(publisher)
        veto_cfg = load_yaml(veto)
    except BridgeConfigError as exc:
        _handle_and_exit(exc)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Re-load the publisher YAML as raw text so we can preserve the
    # author's comments/formatting when we splice in the veto flag.
    publisher_doc: dict[str, Any] = yaml.safe_load(publisher.read_text(encoding="utf-8")) or {}
    publisher_doc.setdefault("safety", {})
    publisher_doc["safety"]["lucas_veto_enabled"] = True

    if in_place:
        linked_path = publisher
    else:
        linked_path = out_dir / f"{publisher.stem}.linked.yaml"
    spec_path = out_dir / "orchestra-spec.yaml"

    for path in (linked_path, spec_path):
        if path.exists() and not force and path != publisher:
            if not typer.confirm(f"{path} already exists. Overwrite?", default=False):
                console.print(Text(f"skipped {path}", style="brand.muted"))
                raise typer.Exit(code=0)

    linked_path.write_text(
        yaml.safe_dump(publisher_doc, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    spec_path.write_text(
        _render_orchestra_spec(
            publisher_path=linked_path,
            publisher_cfg=dict(publisher_cfg),
            veto_path=veto,
            veto_cfg=dict(veto_cfg),
        ),
        encoding="utf-8",
    )

    body = Text()
    body.append("Linked ")
    body.append(str(publisher_cfg["name"]), style="brand.primary")
    body.append(" ⇒ vetoed by ")
    body.append(str(veto_cfg["name"]), style="brand.accent")
    body.append("\n\n")
    body.append("  + ", style="brand.success")
    body.append(f"{linked_path}\n")
    body.append("  + ", style="brand.success")
    body.append(f"{spec_path}\n")
    body.append("\nNext: ", style="brand.primary")
    body.append("`grok-orchestra run orchestra-spec.yaml`")
    body.append(" to exercise the veto gate, or ")
    body.append(f"`grok-build-bridge run {linked_path.name} --dry-run`")
    body.append(" to validate the linked publisher on its own.")
    console.print(
        Panel(
            body,
            title="[brand.success]🔗  link complete[/]",
            border_style="brand.success",
        )
    )


def _render_orchestra_spec(
    *,
    publisher_path: Path,
    publisher_cfg: dict[str, Any],
    veto_path: Path,
    veto_cfg: dict[str, Any],
) -> str:
    """Build a minimal orchestra-spec.yaml that wires the two bridges.

    The format mirrors the curated example at
    ``examples/orchestra-bridge/orchestra-spec.yaml`` — version, named
    agents, an ordered workflow ending in a veto gate, and a handoff
    block that points back at the linked bridge. Fields the linked
    pair don't need (research phases, debate rounds) are omitted so
    the file stays scrutable.
    """
    name = f"{publisher_cfg['name']}-with-veto"
    desc = (
        f"Linked pair generated by `grok-build-bridge link`. "
        f"`{publisher_cfg['name']}` publishes; "
        f"`{veto_cfg['name']}` holds the Lucas veto."
    )
    spec: dict[str, Any] = {
        "version": "1.0",
        "name": name,
        "description": desc,
        "agents": [
            {
                "id": "publisher",
                "bridge_yaml": f"./{publisher_path.name}",
                "role": publisher_cfg.get("description", ""),
            },
            {
                "id": "veto",
                "bridge_yaml": f"./{veto_path.name}",
                "role": veto_cfg.get("description", ""),
            },
        ],
        "workflow": [
            {
                "phase": "publish_with_veto",
                "publisher": "publisher",
                "veto_gate": "veto",
                "on_veto": "abort",
            },
        ],
        "handoff": {
            "bridge_spec": f"./{publisher_path.name}",
            "require_veto_pass": True,
        },
    }
    header = (
        "# Orchestra spec generated by `grok-build-bridge link`.\n"
        "# Edit freely — Bridge will not regenerate this file unless you re-run\n"
        "# `link` with the same outputs.\n\n"
    )
    return header + yaml.safe_dump(spec, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# `fork` command — reconstruct a bridge.yaml from a published artefact
# ---------------------------------------------------------------------------


@app.command("fork")
def fork_cmd(
    source: str = typer.Argument(
        ...,
        help=(
            "Source artefact: a path to a `<slug>-<version>.zip` produced by "
            "`publish`, a path to a manifest.json, or a `bridge.live/p/<sha>.json` URL."
        ),
    ),
    out_dir: Path = typer.Option(
        Path.cwd(),
        "--out",
        "-o",
        help="Destination directory for the reconstructed bridge.yaml.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing bridge.yaml without prompting.",
    ),
) -> None:
    """🍴  Reconstruct a bridge.yaml from a published manifest or passport.

    Three accepted source shapes:

    * A path to a ``<slug>-<version>.zip`` produced by ``publish`` —
      the inverse direction; the zip's ``bridge.yaml`` lands in
      ``--out``.
    * A path to a standalone ``manifest.json`` (or a passport JSON
      from ``bridge.live``) — the embedded ``yaml_text`` is
      reconstructed into a working file.
    * An ``http(s)://`` URL pointing at the same JSON shape — fetched
      via ``httpx``. Public registries (grokagents.dev) are not live
      yet; until they are, paste a ``bridge.live/p/<sha>.json`` URL.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "bridge.yaml"
    if target.exists() and not force:
        if not typer.confirm(f"{target} already exists. Overwrite?", default=False):
            console.print(Text(f"skipped {target}", style="brand.muted"))
            raise typer.Exit(code=0)

    try:
        yaml_text, name = _fetch_fork_source(source)
    except BridgeRuntimeError as exc:
        _handle_and_exit(exc)

    target.write_text(yaml_text, encoding="utf-8")
    body = Text()
    body.append("Forked ")
    body.append(name, style="brand.primary")
    body.append(" from ", style="brand.muted")
    body.append(source)
    body.append("\n\n")
    body.append("  + ", style="brand.success")
    body.append(f"{target}\n")
    body.append("\nNext: ", style="brand.primary")
    body.append("edit the YAML, then run `grok-build-bridge run bridge.yaml --dry-run`.")
    console.print(
        Panel(
            body,
            title="[brand.success]🍴  fork complete[/]",
            border_style="brand.success",
        )
    )


def _fetch_fork_source(source: str) -> tuple[str, str]:
    """Resolve ``source`` to ``(yaml_text, name)``.

    Accepts an HTTP(S) URL, a local path to a zip, or a local path to
    a JSON manifest (either the marketplace ``manifest.json`` or a
    ``bridge.live`` passport JSON — both carry ``yaml_text`` plus the
    agent's ``name``).
    """
    import json
    import zipfile

    # ---- URL ----
    if source.startswith(("http://", "https://")):
        import httpx  # local import: avoids hard dep at module load

        try:
            response = httpx.get(source, follow_redirects=True, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BridgeRuntimeError(
                f"could not fetch {source}: {exc}",
                suggestion="Check the URL or paste a local manifest path instead.",
            ) from exc
        return _yaml_from_json_payload(response.json(), origin=source)

    path = Path(source)
    if not path.exists():
        raise BridgeRuntimeError(
            f"fork source not found: {source}",
            suggestion="Pass a local path or a URL.",
        )

    # ---- ZIP ----
    if path.suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                if "bridge.yaml" not in names:
                    raise BridgeRuntimeError(
                        f"{path} is missing bridge.yaml",
                        suggestion="Forked zips are produced by `grok-build-bridge publish`.",
                    )
                yaml_bytes = zf.read("bridge.yaml")
                manifest_bytes = zf.read("manifest.json") if "manifest.json" in names else b"{}"
        except zipfile.BadZipFile as exc:
            raise BridgeRuntimeError(
                f"{path} is not a valid zip", suggestion="Re-run publish to regenerate."
            ) from exc
        manifest = json.loads(manifest_bytes or b"{}")
        return yaml_bytes.decode("utf-8"), str(manifest.get("name") or path.stem)

    # ---- JSON ----
    if path.suffix == ".json":
        return _yaml_from_json_payload(
            json.loads(path.read_text(encoding="utf-8")), origin=str(path)
        )

    raise BridgeRuntimeError(
        f"unrecognised fork source: {source}",
        suggestion="Use a .zip, a .json manifest, or an http(s):// URL.",
    )


def _yaml_from_json_payload(payload: dict[str, Any], *, origin: str) -> tuple[str, str]:
    """Pull the ``bridge.yaml`` body out of a manifest or passport JSON.

    Two shapes are recognised:

    * Marketplace manifest (``marketplace/manifest.schema.json``) —
      the ``bridge`` block describes the agent but does not embed the
      raw YAML; the ``package`` block carries metadata, not bytes.
      For this case the caller must supply the original zip.
    * ``bridge.live`` passport — exposes ``yaml_text`` directly.

    Future revisions of the marketplace schema will add ``yaml_text``
    so the manifest is round-trippable on its own; until then, the
    passport URL is the recommended path.
    """
    yaml_text = payload.get("yaml_text")
    if isinstance(yaml_text, str) and yaml_text.strip():
        name = str(payload.get("name") or "")
        return yaml_text, name or origin
    raise BridgeRuntimeError(
        f"{origin} does not embed yaml_text",
        suggestion=(
            "Use the published zip, or paste a bridge.live passport URL "
            "(`/p/<sha>.json`) which exposes the raw YAML."
        ),
    )


# ---------------------------------------------------------------------------
# `publish` command — marketplace packaging foundation
# ---------------------------------------------------------------------------


@app.command("publish")
def publish_cmd(
    config: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the bridge YAML file.",
    ),
    package_version: str = typer.Option(
        "0.1.0",
        "--version",
        help="Semantic version of the marketplace package (independent of grok-build-bridge's own version).",
    ),
    out: Path = typer.Option(
        Path("dist") / "marketplace",
        "--out",
        "-o",
        help="Directory to write <slug>-<version>.zip into.",
    ),
    include_build: bool = typer.Option(
        False,
        "--include-build",
        help="Bundle files from generated/<slug>/ into the package (requires a prior `run`).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="🛡️  Build + validate the manifest but do not write the zip.",
    ),
    author_name: str = typer.Option(
        None,
        "--author",
        help="Author display name for the manifest. Defaults to 'Unknown' if omitted.",
    ),
    author_email: str = typer.Option(None, "--author-email", help="Author email for the manifest."),
    license_id: str = typer.Option(
        "Apache-2.0",
        "--license",
        help="SPDX licence id or short name; written as the manifest's `license` field.",
    ),
    homepage: str = typer.Option(None, "--homepage", help="Homepage URL for the published agent."),
    repository: str = typer.Option(None, "--repository", help="Source repository URL."),
    upload_url: str = typer.Option(
        None,
        "--upload",
        help=(
            "After writing the zip, HTTP-PUT it to this URL. Designed for "
            "S3-presigned URLs and any HTTP-PUT-compatible object store. "
            "Falls back to the BRIDGE_REGISTRY_URL env var when omitted."
        ),
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Print full tracebacks on failure."
    ),
) -> None:
    """📦  Package a built agent for the future grokagents.dev marketplace."""
    print_banner(console)
    try:
        from grok_build_bridge.publish import publish

        author_overrides: dict[str, Any] = {}
        if author_name:
            author_overrides["name"] = author_name
        if author_email:
            author_overrides["email"] = author_email

        result = publish(
            config,
            version=package_version,
            out_dir=out,
            include_build=include_build,
            dry_run=dry_run,
            author_overrides=author_overrides or None,
            license_id=license_id,
            homepage=homepage,
            repository=repository,
            upload_url=upload_url,
        )
    except (BridgeConfigError, BridgeRuntimeError) as exc:
        _handle_and_exit(exc, verbose=verbose)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="brand.primary", no_wrap=True)
    table.add_column(style="brand.muted")
    table.add_row("name", result.manifest["name"])
    table.add_row("version", result.manifest["version"])
    table.add_row("target", result.manifest["bridge"]["target"])
    table.add_row("model", result.manifest["bridge"]["model"])
    if result.dry_run:
        table.add_row("status", "🛡️  dry-run (no zip written)")
    else:
        size_kb = result.manifest.get("package", {}).get("size_bytes", 0) / 1024
        table.add_row("package", f"{result.package_path}  ({size_kb:.1f} KB)")
        table.add_row("sha256", result.manifest.get("package", {}).get("sha256", "")[:16] + "…")
        registry = result.manifest.get("marketplace", {}).get("registry_url", "")
        table.add_row("future registry", registry)
        resolved_upload = upload_url or os.environ.get("BRIDGE_REGISTRY_URL")
        if resolved_upload:
            table.add_row("uploaded to", resolved_upload)

    title = "📦  publish — dry-run" if result.dry_run else "📦  publish — package ready"
    console.print(Panel(table, border_style="brand.primary", title=title))

    if not result.dry_run and not (upload_url or os.environ.get("BRIDGE_REGISTRY_URL")):
        console.print(
            "[brand.muted]grokagents.dev registry not live yet. Pass `--upload <url>` "
            "(or set BRIDGE_REGISTRY_URL) to push the zip to your own bucket today.[/]"
        )


# ---------------------------------------------------------------------------
# `doctor` command
# ---------------------------------------------------------------------------


# Severity glyphs reused by the doctor table. Kept module-level so tests can
# substring-match on them without copying the strings.
_DOCTOR_OK: Final[str] = "✓ ok"
_DOCTOR_WARN: Final[str] = "⚠ warn"
_DOCTOR_FAIL: Final[str] = "✗ missing"


@app.command("doctor")
def doctor_cmd(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Print full tracebacks on probe failure."
    ),
) -> None:
    """🩺  Probe the local environment for everything Bridge expects.

    Returns 0 if the required surface (Python, ``xai-sdk``, ``XAI_API_KEY``)
    is healthy and 3 if anything required is missing. Optional surfaces
    (deploy CLIs, ``grok_install``) only contribute warnings.
    """
    rows = list(_collect_doctor_rows())
    table = Table(title="[brand.primary]🩺  Bridge environment[/]", border_style="brand.secondary")
    table.add_column("check", style="brand.primary", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("detail", style="brand.muted")
    for row in rows:
        table.add_row(row.label, _format_status(row.status), row.detail)
    console.print(table)

    failures = [r for r in rows if r.status == "fail"]
    warnings = [r for r in rows if r.status == "warn"]

    if failures:
        body = Text()
        body.append(f"{len(failures)} required check(s) failed.\n\n", style="brand.error")
        for row in failures:
            body.append("  • ", style="brand.muted")
            body.append(row.label, style="brand.primary")
            body.append(f" — {row.fix}\n")
        console.print(
            Panel(body, title="[brand.error]🚫 doctor failed[/]", border_style="brand.error")
        )
        if verbose:
            console.print_exception(show_locals=False)
        raise typer.Exit(code=_EXIT_RUNTIME)

    title = "🩺 doctor — all required checks pass"
    body = Text()
    body.append(f"{len(rows) - len(warnings)} ok", style="brand.success")
    if warnings:
        body.append(f"  ·  {len(warnings)} warning(s) (optional features)\n", style="brand.warn")
        for row in warnings:
            body.append("  • ", style="brand.muted")
            body.append(row.label, style="brand.warn")
            body.append(f" — {row.fix}\n")
    else:
        body.append("  ·  no warnings\n", style="brand.muted")
    console.print(Panel(body, title=f"[brand.success]{title}[/]", border_style="brand.success"))


# Shape of one doctor probe result. ``status`` ∈ {"ok", "warn", "fail"};
# ``fix`` is a one-liner the panel renderer prints when a check fails or
# warns. Plain dataclass-shaped namedtuple to avoid pulling dataclasses into
# this module just for one row type.
class _DoctorRow:  # noqa: D101 — internal struct, name documents purpose
    __slots__ = ("label", "status", "detail", "fix")

    def __init__(self, label: str, status: str, detail: str, fix: str = "") -> None:
        self.label = label
        self.status = status
        self.detail = detail
        self.fix = fix


def _format_status(status: str) -> str:
    """Map a status code to a brand-coloured Rich markup string."""
    if status == "ok":
        return f"[brand.success]{_DOCTOR_OK}[/]"
    if status == "warn":
        return f"[brand.warn]{_DOCTOR_WARN}[/]"
    return f"[brand.error]{_DOCTOR_FAIL}[/]"


def _collect_doctor_rows() -> Iterable[_DoctorRow]:
    """Yield doctor rows in display order. Each yields exactly once."""
    yield _probe_python()
    yield _probe_xai_sdk()
    yield _probe_xai_key()
    yield _probe_x_token()
    yield _probe_grok_install()
    yield _probe_grok_install_home()
    yield _probe_cli("vercel", "for `deploy.target: vercel`")
    yield _probe_cli("railway", "for `deploy.target: railway`")
    yield _probe_cli("flyctl", "for `deploy.target: flyio` (or `fly` symlink)", alt="fly")
    yield _probe_cli("grok-build", "for `build.source: grok-build-cli`")


def _probe_python() -> _DoctorRow:
    version = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        return _DoctorRow("python", "ok", version)
    return _DoctorRow(
        "python",
        "fail",
        version,
        fix="upgrade to Python ≥ 3.10 (Bridge targets 3.10/3.11/3.12).",
    )


def _probe_xai_sdk() -> _DoctorRow:
    try:
        import xai_sdk  # noqa: WPS433
    except ImportError:  # pragma: no cover — pyproject pins the dep
        return _DoctorRow(
            "xai-sdk",
            "fail",
            "not installed",
            fix="pip install xai-sdk (or reinstall grok-build-bridge).",
        )
    version = getattr(xai_sdk, "__version__", "unknown")
    return _DoctorRow("xai-sdk", "ok", str(version))


def _probe_xai_key() -> _DoctorRow:
    if os.environ.get("XAI_API_KEY"):
        return _DoctorRow("XAI_API_KEY", "ok", "set")
    return _DoctorRow(
        "XAI_API_KEY",
        "fail",
        "unset",
        fix="export XAI_API_KEY=sk-... (get one at https://console.x.ai).",
    )


def _probe_x_token() -> _DoctorRow:
    if os.environ.get("X_BEARER_TOKEN"):
        return _DoctorRow("X_BEARER_TOKEN", "ok", "set")
    return _DoctorRow(
        "X_BEARER_TOKEN",
        "warn",
        "unset",
        fix="optional — only needed for `deploy.target: x`.",
    )


def _probe_grok_install() -> _DoctorRow:
    try:
        import grok_install.runtime  # noqa: F401, WPS433
    except ImportError:
        return _DoctorRow(
            "grok_install (python package)",
            "warn",
            "not importable",
            fix="optional — `pip install grok-install` to enable real `deploy.target: x`.",
        )
    return _DoctorRow("grok_install (python package)", "ok", "importable")


def _probe_grok_install_home() -> _DoctorRow:
    home = os.environ.get("GROK_INSTALL_HOME")
    if not home:
        return _DoctorRow(
            "GROK_INSTALL_HOME",
            "warn",
            "unset",
            fix="optional — point at a local checkout of grok-install-ecosystem.",
        )
    if Path(home).is_dir():
        return _DoctorRow("GROK_INSTALL_HOME", "ok", home)
    return _DoctorRow(
        "GROK_INSTALL_HOME",
        "warn",
        f"set but not a directory: {home}",
        fix="point GROK_INSTALL_HOME at an existing directory or unset it.",
    )


def _probe_cli(name: str, purpose: str, *, alt: str | None = None) -> _DoctorRow:
    binary = shutil.which(name) or (shutil.which(alt) if alt else None)
    if binary:
        return _DoctorRow(name, "ok", binary)
    return _DoctorRow(
        name,
        "warn",
        "not on PATH",
        fix=f"optional — install only if you need it ({purpose}).",
    )


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
