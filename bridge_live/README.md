# bridge.live

> **Drop a `bridge.yaml`, get a public agent passport.**
> Backed by [`grok-build-bridge`](https://github.com/AgentMindCloud/grok-build-bridge).

`bridge.live` is a tiny FastAPI service that turns any `bridge.yaml`
into a shareable URL with the parsed config, safety verdict, deploy
target, model, and the exact CLI command to run it locally.

It runs **phases 1 (parse + validate) and 3 (static safety scan) only** —
no Grok calls, no XAI key required, no deploys. That makes it cheap to
host and safe to point at strangers.

## Routes

| Path | What it does |
| --- | --- |
| `GET /` | Paste-or-upload landing page. |
| `POST /p` | Render a passport from a posted YAML; redirects to the passport URL. |
| `GET /p/<sha8>` | Public, share-stable passport page. |
| `GET /showcase` | Gallery seeded with the eight bundled templates. |
| `GET /launch?topic=...` | Pre-fills the editor with a YAML scaffolded for the given topic. |
| `GET /healthz` | Liveness probe, returns `ok`. |

## Run it locally

```bash
# From the repo root:
pip install -e ".[live]"

# One command, dev server with auto-reload:
uvicorn bridge_live.app:app --reload
# → http://127.0.0.1:8000
```

The first request seeds `./.passports/` with the 8 bundled template
passports. Pass `BRIDGE_LIVE_HOME=/some/dir` to point persistence
elsewhere.

## Run it as a container

```bash
docker build -f bridge_live/Dockerfile -t bridge-live .
docker run --rm -p 8080:8080 -v "$PWD/.passports:/data/passports" bridge-live
```

The Dockerfile pins `python:3.12-slim`, exposes `8080`, mounts
`/data/passports` as a volume for persistence, and ships a `/healthz`
HEALTHCHECK so any orchestrator can probe it.

## Deploy targets — one-liners

> All four hosts below accept a Dockerfile out of the box. The service
> is stateless apart from the passport store; mount any persistent
> volume / object store at `/data/passports` if you want SHAs to
> survive a redeploy.

### Fly.io

```bash
flyctl launch --no-deploy --dockerfile bridge_live/Dockerfile
flyctl volumes create passports --size 1
# Add to fly.toml:
#   [mounts]
#   source = "passports"
#   destination = "/data/passports"
flyctl deploy
```

### Render

Connect the repo, pick "Web Service", set:

- **Build command:** _(leave empty — Dockerfile handles it)_
- **Dockerfile path:** `bridge_live/Dockerfile`
- **Health check path:** `/healthz`

### Railway

```bash
railway up
railway variables set BRIDGE_LIVE_HOME=/data/passports
```

Add a volume mount at `/data/passports` in the Railway dashboard.

### Vercel (Python runtime)

Vercel does not accept this Dockerfile directly — wrap `bridge_live.app:app`
in a Vercel Python serverless function (`api/index.py`):

```python
from bridge_live.app import app
```

Then add `vercel.json` rewrites that route every path to `api/index.py`.
Passports are ephemeral on Vercel; point `BRIDGE_LIVE_HOME` at a
mounted blob store if you want them to persist.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `BRIDGE_LIVE_HOME` | `./.passports` | Where passport JSON files are written. |
| `PORT` | `8080` (Docker) / `8000` (uvicorn dev) | TCP port. |

## Security posture

`bridge.live` accepts arbitrary YAML from the public internet. Two
mitigations in place:

- The pipeline only parses + statically scans. **No Grok calls. No
  deploys. No subprocess execution.**
- `grok_build_bridge.parser.load_yaml` uses a strict Draft 2020-12
  validator with `additionalProperties: false` on every object — unknown
  keys are rejected before any renderer touches them.
- A 256 KiB ceiling on the YAML payload prevents memory blow-ups from
  abusive pastes (`POST /p` returns 413 above the limit).

## Why this exists

`bridge.live` is the acquisition surface in
[the growth plan](../README.md#-roadmap):

- **Every passport URL is a tweet.** Share an agent without asking the
  reader to install anything.
- **Every share is a billboard for `pip install grok-build-bridge`** —
  the passport's "Run locally" block points at the CLI.
- **The showcase is seeded** so day-one visitors see real, runnable
  agents — no empty-state trap.

## Limitations (v0.1)

- No XAI key handoff yet — agents with `build.source: grok` are
  inspectable but the actual code-generation step is not previewed.
- No upload endpoint to grokagents.dev — the passport is the share
  primitive; real publishing waits for `grok-build-bridge publish --upload`
  in v0.3.0.
- Passports are file-backed; the store is not multi-writer safe. A
  Postgres backend will land when traffic justifies it.

Apache 2.0 — same licence as the parent repo.
