"""Grok-prompt → code generator.

Turns a validated bridge config into a concrete codebase on disk. Three
``build.source`` modes are supported:

* ``grok`` — stream ``grok-4.20-0309`` via :class:`XAIClient`, extract a
  fenced code block, and write it to ``generated/<name>/<entrypoint>``.
* ``local`` — skip generation. The caller has already produced the file;
  we locate it (alongside the YAML, or pre-existing under ``generated/``)
  and validate that it is there.
* ``grok-build-cli`` — write the prompt to ``build.prompt`` under the
  generated dir and shell out to the ecosystem CLI when available. If the
  binary cannot be found we log the substitution and fall back to the
  ``grok`` path so the run still makes progress.

In every mode we emit a ``bridge.manifest.json`` alongside the code with
timestamp, model, prompt hash, token usage, and the file list. That
manifest is what :class:`SafetyReport` and the deploy layer consume — a
single machine-readable artefact of the build.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from grok_build_bridge._console import console, info, warn
from grok_build_bridge.xai_client import (
    ALLOWED_MODELS,
    BridgeRuntimeError,
    XAIClient,
)

_DEFAULT_GENERATED_ROOT: Final[Path] = Path("generated")
_MANIFEST_FILE: Final[str] = "bridge.manifest.json"
_PROMPT_FILE: Final[str] = "build.prompt"

# Extract the first fenced code block from a Grok response. We accept both
# ```<lang> … ``` and a bare ``` … ``` fence because Grok sometimes omits the
# language hint when the user pre-specified it in the prompt.
_FENCED_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)```",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class BuilderError(BridgeRuntimeError):
    """Raised when the builder cannot produce a codebase."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_generated_dir(name: str, *, base: Path | None = None) -> Path:
    """Return ``<base>/generated/<name>`` (defaulting ``base`` to cwd)."""
    root = (base or Path.cwd()) / _DEFAULT_GENERATED_ROOT / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_manifest(
    path: Path,
    *,
    name: str,
    source: str,
    model: str,
    prompt: str,
    entrypoint: str,
    generated_chars: int,
    files: Sequence[Path],
) -> Path:
    """Write ``bridge.manifest.json`` and return its path.

    The token count is an estimate (``chars / 4``) rather than a read from
    the SDK's ``Response.usage``; the streaming accumulator does not track
    per-chunk usage in v0.1 and we prefer a cheap approximation over
    plumbing the full metric through. The downstream safety report uses
    the same heuristic, so the numbers remain internally consistent.
    """
    manifest = {
        "name": name,
        "source": source,
        "model": model,
        "entrypoint": entrypoint,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if prompt
        else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_usage_estimate": max(1, int(generated_chars / 4)) if generated_chars else 0,
        "generated_chars": generated_chars,
        "files": sorted(str(f.relative_to(path)) for f in files if f.is_file()),
    }
    manifest_path = path / _MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def _extract_code(streamed_text: str) -> str:
    """Pull the first fenced code block out of a Grok response.

    If no fenced block is present we return the raw text — Grok sometimes
    answers pure code without a fence, and refusing to handle that case
    would send users back to the prompt for no good reason.
    """
    match = _FENCED_BLOCK.search(streamed_text)
    if match is None:
        return streamed_text.strip() + "\n"
    return match.group(1).rstrip() + "\n"


def _tools_for(required_tools: Sequence[str] | None) -> list[dict[str, Any]] | None:
    """Translate the config's tool slugs to xai-sdk tool objects.

    The SDK accepts a ``Sequence[Tool]`` where ``Tool`` is an opaque
    protobuf. For v0.1 we pass a plain dict payload: the real SDK will
    ignore unknown keys and our fake SDK in tests only inspects identity.
    When the real deployment path lights up we will swap this to the
    SDK's native constructors in one place.
    """
    if not required_tools:
        return None
    return [{"type": str(name)} for name in required_tools]


def _stream_generation(
    client: XAIClient,
    *,
    model: str,
    prompt: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
) -> str:
    """Stream a completion with a Rich spinner and return the full text.

    The spinner renders via :class:`rich.live.Live` rather than
    :class:`rich.progress.Progress` because Progress is optimised for
    determinate tasks with a known total; here we only know when the
    stream ends.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior engineer producing a single, runnable file "
                "in response to a build request. Output ONE fenced code block "
                "containing the complete file — nothing else."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    spinner = Spinner("dots", text=Text("🎯 Grok is building...", style="cyan bold"))
    full_text_parts: list[str] = []
    last_chunk_len = 0

    with Live(
        Panel(spinner, border_style="cyan"),
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        for response, _chunk in client.stream_chat(
            model=model,
            messages=messages,
            tools=tools,
            reasoning_effort="medium",
            max_tokens=max_tokens,
        ):
            # ``response.content`` accumulates the full text so far — we keep
            # only the newest span to avoid re-rendering megabytes when the
            # output gets long.
            current = getattr(response, "content", "") or ""
            if len(current) > last_chunk_len:
                new_text = current[last_chunk_len:]
                full_text_parts.append(new_text)
                last_chunk_len = len(current)
                # Update the live panel with a short progress footer.
                live.update(
                    Panel(
                        Text.from_markup(
                            f"[cyan bold]🎯 Grok is building...[/] "
                            f"[dim]({last_chunk_len} chars so far)[/]"
                        ),
                        border_style="cyan",
                    )
                )

    return "".join(full_text_parts)


# ---------------------------------------------------------------------------
# Source-mode dispatchers
# ---------------------------------------------------------------------------


def _run_grok_source(
    *,
    config: dict[str, Any],
    client: XAIClient,
    gen_dir: Path,
    entrypoint: str,
) -> tuple[str, str]:
    """Generate via Grok. Returns ``(written_code, model_id)``."""
    prompt = config["build"].get("grok_prompt") or ""
    if not prompt:
        raise BuilderError(
            "build.source is 'grok' but build.grok_prompt is empty",
            suggestion="Add a grok_prompt to the bridge YAML.",
        )
    model = config["agent"]["model"]
    if model not in ALLOWED_MODELS:
        raise BuilderError(
            f"agent.model {model!r} is not in the supported set",
            suggestion=f"Use one of {sorted(ALLOWED_MODELS)}.",
        )
    max_tokens = int(
        (config.get("safety") or {}).get("max_tokens_per_run") or 8000
    )
    tools = _tools_for(config["build"].get("required_tools"))

    streamed = _stream_generation(
        client,
        model=model,
        prompt=prompt,
        tools=tools,
        max_tokens=max_tokens,
    )
    code = _extract_code(streamed)
    (gen_dir / entrypoint).parent.mkdir(parents=True, exist_ok=True)
    (gen_dir / entrypoint).write_text(code, encoding="utf-8")
    return code, model


def _run_local_source(
    *,
    config: dict[str, Any],
    gen_dir: Path,
    entrypoint: str,
    yaml_dir: Path | None,
) -> None:
    """Validate that the entrypoint already exists, copying from yaml_dir if needed."""
    target = gen_dir / entrypoint

    if target.is_file():
        info(f"local source: using existing {target}")
        return

    # Fall back to siblings of the YAML file — this lets a repo ship
    # ``examples/hello.yaml`` + ``examples/hello/main.py`` and have the
    # bridge pick up the file without a second config knob.
    candidates: list[Path] = []
    if yaml_dir is not None:
        candidates.extend(
            [
                yaml_dir / config["name"] / entrypoint,
                yaml_dir / entrypoint,
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
            info(f"local source: copied {candidate} → {target}")
            return

    raise BuilderError(
        f"local source requires {entrypoint} to exist under {gen_dir} "
        f"or alongside the YAML; none of {candidates} was found",
        suggestion=(
            f"Place your code at {target} or switch build.source to 'grok'."
        ),
    )


def _run_grok_build_cli_source(
    *,
    config: dict[str, Any],
    client: XAIClient,
    gen_dir: Path,
    entrypoint: str,
) -> tuple[str, str]:
    """Shell out to the grok-build CLI if present, else fall back to grok."""
    prompt = config["build"].get("grok_prompt") or ""
    (gen_dir / _PROMPT_FILE).write_text(prompt, encoding="utf-8")

    binary = shutil.which("grok-build")
    if binary is None:
        warn(
            "grok-build CLI not found on PATH — falling back to direct Grok "
            "generation for this run."
        )
        return _run_grok_source(
            config=config, client=client, gen_dir=gen_dir, entrypoint=entrypoint
        )

    cmd = [
        binary,
        "run",
        "--project",
        str(gen_dir),
        "--entry",
        entrypoint,
    ]
    info(f"shelling out: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)  # noqa: S603 — cmd is fully controlled
    except subprocess.CalledProcessError as exc:
        raise BuilderError(
            f"grok-build CLI exited with {exc.returncode}",
            suggestion="Inspect the CLI output above, or fall back to source: grok.",
        ) from exc

    code_path = gen_dir / entrypoint
    if not code_path.is_file():
        raise BuilderError(
            f"grok-build finished but {code_path} does not exist",
            suggestion="Check the CLI's --entry argument.",
        )
    return code_path.read_text(encoding="utf-8"), config["agent"]["model"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_code(
    config: dict[str, Any],
    client: XAIClient | None = None,
    *,
    yaml_dir: Path | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Generate (or locate) the agent codebase for ``config``.

    Args:
        config: Validated bridge config dict (output of
            :func:`grok_build_bridge.parser.load_yaml`, unfrozen). Expected
            keys: ``name``, ``build``, ``agent``, and optionally ``safety``.
        client: XAIClient used for the ``grok`` and ``grok-build-cli``
            fallback paths. Required for those modes; unused for ``local``.
        yaml_dir: Directory containing the source YAML file, used only by
            the ``local`` mode to locate sibling code.
        base_dir: Override for the project root. Defaults to ``cwd``; the
            generated tree lives at ``<base_dir>/generated/<name>/``.

    Returns:
        Path to the generated agent directory (``generated/<name>/``).

    Raises:
        BuilderError: If the requested source mode cannot produce code.
    """
    name = config["name"]
    build = config["build"]
    source = build["source"]
    entrypoint = build["entrypoint"]

    gen_dir = _resolve_generated_dir(name, base=base_dir)
    info(f"build source: {source}  →  {gen_dir}")

    written_code = ""
    model_used = config["agent"]["model"]

    if source == "local":
        _run_local_source(
            config=config,
            gen_dir=gen_dir,
            entrypoint=entrypoint,
            yaml_dir=yaml_dir,
        )
        written_code = (gen_dir / entrypoint).read_text(encoding="utf-8")
    elif source == "grok":
        if client is None:
            raise BuilderError(
                "build.source is 'grok' but no XAIClient was provided",
                suggestion="Pass a client or set build.source to 'local'.",
            )
        written_code, model_used = _run_grok_source(
            config=config, client=client, gen_dir=gen_dir, entrypoint=entrypoint
        )
    elif source == "grok-build-cli":
        if client is None:
            raise BuilderError(
                "build.source 'grok-build-cli' needs an XAIClient for its fallback path",
                suggestion="Pass a client or set build.source to 'local'.",
            )
        written_code, model_used = _run_grok_build_cli_source(
            config=config, client=client, gen_dir=gen_dir, entrypoint=entrypoint
        )
    else:
        raise BuilderError(f"unknown build.source {source!r}")

    files = [p for p in gen_dir.rglob("*") if p.is_file() and p.name != _MANIFEST_FILE]
    _write_manifest(
        gen_dir,
        name=name,
        source=source,
        model=model_used,
        prompt=build.get("grok_prompt") or "",
        entrypoint=entrypoint,
        generated_chars=len(written_code),
        files=files,
    )
    return gen_dir
