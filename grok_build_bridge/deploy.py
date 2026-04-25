"""Deploy layer — ship a built agent to its configured target.

Dispatches on ``deploy.target`` from the bridge config:

* ``x``    — hand off to ``grok_install.runtime.deploy_to_x`` when that
  package is installed, otherwise write the payload to
  ``generated/deploy_payload.json`` via the Session 1 fallback stub.
* ``vercel``  — run ``vercel --prod --yes`` in the generated directory if
  the CLI is on ``PATH``.
* ``render``  — write a minimal ``render.yaml`` and print deploy-via-git
  instructions.
* ``railway`` — write a minimal ``railway.json`` and shell out to
  ``railway up --detach`` when the CLI is on ``PATH``.
* ``flyio``   — write a minimal ``fly.toml`` and shell out to
  ``flyctl deploy --remote-only`` when the CLI is on ``PATH``.
* ``local``   — print the local run command for the generated entrypoint.

Before any ``x`` deploy we audit the announcement content with
:func:`grok_build_bridge.safety.audit_x_post`. If the audit fails and
either ``safety.audit_before_post`` (default true) or
``safety.lucas_veto_enabled`` is set, we block with
:class:`BridgeSafetyError`.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from grok_build_bridge._console import info, section, warn
from grok_build_bridge.safety import BridgeSafetyError, audit_x_post
from grok_build_bridge.xai_client import BridgeRuntimeError, XAIClient

logger: Final[logging.Logger] = logging.getLogger(__name__)

DeployFn = Callable[[dict[str, Any]], Any]

_DRY_RUN_PAYLOAD_PATH: Final[Path] = Path("generated") / "deploy_payload.json"
_RENDER_YAML_NAME: Final[str] = "render.yaml"
_RAILWAY_JSON_NAME: Final[str] = "railway.json"
_FLY_TOML_NAME: Final[str] = "fly.toml"
_MANIFEST_FILE: Final[str] = "bridge.manifest.json"


# ---------------------------------------------------------------------------
# Fallback stub for the ``x`` path when grok_install is absent
# ---------------------------------------------------------------------------


def _dry_run_stub(payload: dict[str, Any]) -> dict[str, Any]:
    """Write ``payload`` to ``generated/deploy_payload.json`` and return meta."""
    warn("⚠️  grok_install not installed — dry-run only")
    _DRY_RUN_PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DRY_RUN_PAYLOAD_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    logger.info("dry-run payload written to %s", _DRY_RUN_PAYLOAD_PATH)
    return {"dry_run": True, "path": str(_DRY_RUN_PAYLOAD_PATH)}


deploy_to_x: DeployFn
try:
    from grok_install.runtime import deploy_to_x as _deploy_to_x

    deploy_to_x = _deploy_to_x
    logger.info("deploy path: grok_install.runtime.deploy_to_x")
except ImportError:
    deploy_to_x = _dry_run_stub
    logger.info("deploy path: local dry-run stub (grok_install not installed)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _announcement_for(config: dict[str, Any]) -> str:
    """Return the content the agent will announce on X when it deploys.

    v0.1 policy: use the ``description`` field (already schema-capped to
    280 characters so it fits in one post) as the pre-deploy audit target.
    A future revision can let users pin an explicit ``deploy.post_content``
    string; for now description is the natural launch blurb.
    """
    return str(config.get("description") or "").strip()


def _should_audit(config: dict[str, Any]) -> bool:
    safety = config.get("safety") or {}
    # Either gate turns the audit on; the schema defaults audit_before_post
    # to True so the caller has to opt OUT explicitly.
    return bool(safety.get("audit_before_post", True) or safety.get("lucas_veto_enabled", False))


def _run_x_audit(
    config: dict[str, Any],
    *,
    client: XAIClient | None,
) -> None:
    """Audit the announcement text; raise on a fail that the gates require us to block."""
    content = _announcement_for(config)
    if not content:
        info("no announcement text to audit — skipping pre-deploy audit")
        return
    if not _should_audit(config):
        info("audit_before_post and lucas_veto_enabled are both off — skipping audit")
        return

    report = audit_x_post(content, dict(config), client=client)
    if report.safe:
        info("🛡️  pre-deploy X-post audit: ✅ clean")
        return

    safety = config.get("safety") or {}
    if safety.get("lucas_veto_enabled") or safety.get("audit_before_post", True):
        raise BridgeSafetyError(
            f"pre-deploy X-post audit blocked the launch ({len(report.issues)} issue(s))",
            suggestion=(
                "Edit description/personality to address the report, or rerun "
                "with safety.audit_before_post=false to override."
            ),
        )


# ---------------------------------------------------------------------------
# Target dispatchers
# ---------------------------------------------------------------------------


def _deploy_x(
    generated_dir: Path,
    config: dict[str, Any],
    *,
    client: XAIClient | None,
) -> str:
    _run_x_audit(config, client=client)
    manifest = _read_manifest(generated_dir)
    payload: dict[str, Any] = {
        "name": config["name"],
        "description": config.get("description"),
        "agent": config.get("agent"),
        "deploy": config.get("deploy"),
        "generated_dir": str(generated_dir),
        "manifest": manifest,
    }
    result = deploy_to_x(payload)
    # The real deploy_to_x returns something shaped by the ecosystem; the
    # stub returns a dict. Normalise to a URL/path string for the caller.
    if isinstance(result, dict):
        url = result.get("url") or result.get("path") or str(generated_dir)
        return str(url)
    return str(result) if result is not None else f"x://{config['name']}"


def _deploy_vercel(generated_dir: Path, config: dict[str, Any]) -> str:
    binary = shutil.which("vercel")
    if binary is None:
        warn("vercel CLI not found on PATH — skipping deploy and printing next steps instead.")
        info(
            "Install the CLI with `npm i -g vercel`, then run "
            f"`vercel --prod --yes` inside {generated_dir}."
        )
        return f"vercel://pending/{config['name']}"

    info(f"shelling out: {binary} --prod --yes (cwd={generated_dir})")
    try:
        completed = subprocess.run(
            [binary, "--prod", "--yes"],
            cwd=generated_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BridgeRuntimeError(
            f"vercel deploy failed (exit {exc.returncode}): {exc.stderr.strip()}",
            suggestion="Run `vercel login` and retry, or inspect the vercel CLI output.",
        ) from exc

    stdout = (completed.stdout or "").strip().splitlines()
    # The Vercel CLI prints the deployment URL on its last line.
    return stdout[-1] if stdout else f"vercel://{config['name']}"


def _deploy_render(generated_dir: Path, config: dict[str, Any]) -> str:
    render_yaml = generated_dir / _RENDER_YAML_NAME
    render_yaml.write_text(_render_yaml_body(config), encoding="utf-8")
    info(f"wrote {render_yaml}")
    info(
        "Render deploys happen via git push — commit the generated dir and "
        "push to a repo connected to Render."
    )
    return f"render://pending/{config['name']}"


def _deploy_railway(generated_dir: Path, config: dict[str, Any]) -> str:
    railway_json = generated_dir / _RAILWAY_JSON_NAME
    railway_json.write_text(_railway_json_body(config), encoding="utf-8")
    info(f"wrote {railway_json}")

    binary = shutil.which("railway")
    if binary is None:
        warn("railway CLI not found on PATH — skipping deploy and printing next steps instead.")
        info(
            "Install the CLI with `npm i -g @railway/cli`, then run "
            f"`railway login && railway link && railway up --detach` inside {generated_dir}."
        )
        return f"railway://pending/{config['name']}"

    info(f"shelling out: {binary} up --detach (cwd={generated_dir})")
    try:
        completed = subprocess.run(
            [binary, "up", "--detach"],
            cwd=generated_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BridgeRuntimeError(
            f"railway deploy failed (exit {exc.returncode}): {exc.stderr.strip()}",
            suggestion="Run `railway login` and `railway link <project>` inside the generated dir, then retry.",
        ) from exc

    stdout = (completed.stdout or "").strip().splitlines()
    # Railway prints a "Deployment live at <url>" line; surface the last non-empty line.
    return stdout[-1] if stdout else f"railway://{config['name']}"


def _deploy_flyio(generated_dir: Path, config: dict[str, Any]) -> str:
    fly_toml = generated_dir / _FLY_TOML_NAME
    fly_toml.write_text(_fly_toml_body(config), encoding="utf-8")
    info(f"wrote {fly_toml}")

    # The Fly CLI is `flyctl`, but legacy installs symlink it as `fly`.
    binary = shutil.which("flyctl") or shutil.which("fly")
    if binary is None:
        warn("flyctl not found on PATH — skipping deploy and printing next steps instead.")
        info(
            "Install with `brew install flyctl` (macOS) or `curl -L https://fly.io/install.sh | sh`, "
            f"then run `flyctl launch --no-deploy && flyctl deploy --remote-only` inside {generated_dir}."
        )
        return f"flyio://pending/{config['name']}"

    info(f"shelling out: {binary} deploy --remote-only (cwd={generated_dir})")
    try:
        completed = subprocess.run(
            [binary, "deploy", "--remote-only"],
            cwd=generated_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BridgeRuntimeError(
            f"flyio deploy failed (exit {exc.returncode}): {exc.stderr.strip()}",
            suggestion="Run `flyctl auth login` and `flyctl apps create <name>`, then retry.",
        ) from exc

    stdout = (completed.stdout or "").strip().splitlines()
    return stdout[-1] if stdout else f"flyio://{config['name']}"


def _deploy_local(generated_dir: Path, config: dict[str, Any]) -> str:
    entrypoint = (config.get("build") or {}).get("entrypoint") or "main.py"
    language = (config.get("build") or {}).get("language") or "python"
    runner = {"python": "python", "typescript": "node", "go": "go run"}.get(language, "python")
    cmd = f"{runner} {generated_dir / entrypoint}"
    info(f"local target — run it with:  {cmd}")
    return str(generated_dir)


def _render_yaml_body(config: dict[str, Any]) -> str:
    """Minimal render.yaml based on the bridge config."""
    name = config["name"]
    language = (config.get("build") or {}).get("language") or "python"
    entrypoint = (config.get("build") or {}).get("entrypoint") or "main.py"
    start_cmd = {
        "python": f"python {entrypoint}",
        "typescript": f"node {entrypoint}",
        "go": f"go run {entrypoint}",
    }.get(language, f"python {entrypoint}")
    schedule = (config.get("deploy") or {}).get("schedule")
    schedule_block = f"    schedule: '{schedule}'\n" if schedule else ""
    return (
        "services:\n"
        f"  - type: worker\n"
        f"    name: {name}\n"
        f"    env: {language}\n"
        f"    buildCommand: ''\n"
        f"    startCommand: {start_cmd}\n"
        f"{schedule_block}"
    )


def _railway_json_body(config: dict[str, Any]) -> str:
    """Minimal railway.json based on the bridge config.

    Railway's Nixpacks builder auto-detects the language; we just pin the
    start command so the deploy is reproducible. Schedules on Railway are
    set per-service in the dashboard rather than the config file, so we
    leave that out and surface the cron string in the printed instructions.
    """
    language = (config.get("build") or {}).get("language") or "python"
    entrypoint = (config.get("build") or {}).get("entrypoint") or "main.py"
    start_cmd = {
        "python": f"python {entrypoint}",
        "typescript": f"node {entrypoint}",
        "go": f"go run {entrypoint}",
    }.get(language, f"python {entrypoint}")
    body: dict[str, Any] = {
        "$schema": "https://railway.app/railway.schema.json",
        "build": {"builder": "NIXPACKS"},
        "deploy": {
            "startCommand": start_cmd,
            "restartPolicyType": "ON_FAILURE",
            "restartPolicyMaxRetries": 3,
        },
    }
    return json.dumps(body, indent=2) + "\n"


def _fly_toml_body(config: dict[str, Any]) -> str:
    """Minimal fly.toml based on the bridge config.

    Fly's TOML schema is large; we emit the smallest valid stanza that
    covers builder + process + service. Cron-style schedules are not a
    fly.toml field — they are configured via ``flyctl machine run
    --schedule`` after deploy — so we surface the cron string as a comment.
    """
    name = config["name"]
    language = (config.get("build") or {}).get("language") or "python"
    entrypoint = (config.get("build") or {}).get("entrypoint") or "main.py"
    start_cmd = {
        "python": f"python {entrypoint}",
        "typescript": f"node {entrypoint}",
        "go": f"go run {entrypoint}",
    }.get(language, f"python {entrypoint}")
    schedule = (config.get("deploy") or {}).get("schedule")
    schedule_comment = (
        f"# schedule = '{schedule}'  # set via `flyctl machine run --schedule` after deploy\n"
        if schedule
        else ""
    )
    return (
        f"# fly.toml — generated by grok-build-bridge\n"
        f"app = '{name}'\n"
        f"primary_region = 'iad'\n"
        f"\n"
        f"[build]\n"
        f"  builder = 'paketobuildpacks/builder:base'\n"
        f"\n"
        f"[processes]\n"
        f'  app = "{start_cmd}"\n'
        f"\n"
        f"[[services]]\n"
        f"  protocol = 'tcp'\n"
        f"  internal_port = 8080\n"
        f"  processes = ['app']\n"
        f"{schedule_comment}"
    )


def _read_manifest(generated_dir: Path) -> dict[str, Any]:
    path = generated_dir / _MANIFEST_FILE
    if not path.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgeRuntimeError(
            f"bridge.manifest.json is not valid JSON: {path}",
            suggestion="Re-run the bridge to regenerate the manifest.",
        ) from exc
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def deploy_to_target(
    generated_dir: Path,
    config: dict[str, Any],
    *,
    client: XAIClient | None = None,
) -> str:
    """🎤 Deploy the agent at ``generated_dir`` to its configured target.

    Args:
        generated_dir: Output of :func:`grok_build_bridge.builder.generate_code`.
        config: Validated bridge config (plain dict — the runtime unfreezes
            the :class:`MappingProxyType` before passing it in).
        client: Optional :class:`XAIClient` used for the pre-deploy X-post
            audit. Tests pass a fake; CLI runs a fresh client.

    Returns:
        A URL or path string identifying the deploy target.

    Raises:
        BridgeSafetyError: If the X-post audit blocks the deploy.
        BridgeRuntimeError: On subprocess failures or unknown targets.
    """
    section("🎤  deploy")
    deploy_cfg = dict(config.get("deploy") or {})
    target = deploy_cfg.get("target", "x")

    if target == "x":
        return _deploy_x(generated_dir, config, client=client)
    if target == "vercel":
        return _deploy_vercel(generated_dir, config)
    if target == "render":
        return _deploy_render(generated_dir, config)
    if target == "railway":
        return _deploy_railway(generated_dir, config)
    if target == "flyio":
        return _deploy_flyio(generated_dir, config)
    if target == "local":
        return _deploy_local(generated_dir, config)

    raise BridgeRuntimeError(
        f"unknown deploy.target {target!r}",
        suggestion="Use one of: x, vercel, render, railway, flyio, local.",
    )
