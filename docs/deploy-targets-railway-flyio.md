# Railway & Fly.io deploy targets

> Added in v0.2.0. Companion to [`docs/build-bridge.md`](build-bridge.md).

Both targets follow the same pattern as `vercel`: Bridge writes a config
file next to the generated agent, then shells out to the host's CLI when
that CLI is on `PATH`. If the CLI is missing, Bridge prints the manual
deploy steps and exits with a `<target>://pending/<name>` placeholder URL —
safe for CI dry-runs.

## Railway (`deploy.target: railway`)

```yaml
deploy:
  target: railway
  runtime: grok-install
  post_to_x: false
  schedule: "0 */6 * * *"   # informational; Railway schedules live in the dashboard
  safety_scan: true
```

- **Config Bridge writes:** `railway.json` (NIXPACKS builder + start command + ON_FAILURE restart).
- **CLI Bridge calls:** `railway up --detach`.
- **Pre-flight:** `npm i -g @railway/cli` → `railway login` → `railway link <project>` (or `railway init`).
- **Pending placeholder URL:** `railway://pending/<name>`.

The cron string in `deploy.schedule` is **not** consumed by `railway.json` —
Railway schedules are configured per-service in the dashboard. Bridge prints
the schedule as a hint so you can paste it into the Railway UI.

Live worker template: [`grok_build_bridge/templates/railway-worker-bot.yaml`](../grok_build_bridge/templates/railway-worker-bot.yaml)
(`grok-build-bridge init railway-worker-bot`).

Smoke test: [`examples/railway.yaml`](../examples/railway.yaml).

## Fly.io (`deploy.target: flyio`)

```yaml
deploy:
  target: flyio
  runtime: grok-install
  post_to_x: false
  safety_scan: true
```

- **Config Bridge writes:** `fly.toml` (paketo buildpack + processes + 8080 service).
- **CLI Bridge calls:** `flyctl deploy --remote-only` (also accepts a `fly` symlink).
- **Pre-flight:** `brew install flyctl` (macOS) or `curl -L https://fly.io/install.sh | sh`, then `flyctl auth login`, then `flyctl apps create <name>` (the `<name>` must match the bridge config's `name:` field).
- **Pending placeholder URL:** `flyio://pending/<name>`.

Cron-style schedules are not a `fly.toml` field. If you set
`deploy.schedule` it is emitted as a comment in the generated `fly.toml`;
configure the schedule via `flyctl machine run --schedule` after deploy.

Edge template: [`grok_build_bridge/templates/flyio-edge-bot.yaml`](../grok_build_bridge/templates/flyio-edge-bot.yaml)
(`grok-build-bridge init flyio-edge-bot`).

Smoke test: [`examples/flyio.yaml`](../examples/flyio.yaml).

## Choosing between Railway and Fly.io

| Criterion          | Railway                         | Fly.io                              |
| ------------------ | ------------------------------- | ----------------------------------- |
| Builder            | NIXPACKS auto-detect            | Paketo buildpack (or Dockerfile)    |
| Cold start         | warm worker, no cold starts     | Machine cold start ~200ms           |
| Best for           | continuous workers, schedulers  | latency-sensitive replies, edge     |
| Free tier          | hobby plan ~500 hrs/mo          | 3 small Machines, 256 MB each       |
| Schedule mechanism | dashboard service settings      | `flyctl machine run --schedule`     |
| Bridge fast-path   | `railway up --detach`           | `flyctl deploy --remote-only`       |

Both pass through the same Bridge audit (static + Grok LLM) before any deploy
runs. Both honour `--dry-run` to exercise phases 1–3 without writing a
single byte to the host.
