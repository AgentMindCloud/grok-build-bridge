# Build Bridge Guide

Deep-dive reference for `grok-build-bridge`. Covers every YAML field, the
full phase-by-phase flow, and the ten most common errors with fixes.

- [What is the Build Bridge?](#what-is-the-build-bridge)
- [Writing a `bridge.yaml`](#writing-a-bridgeyaml)
- [End-to-end flow](#end-to-end-flow)
- [Safety guarantees](#safety-guarantees)
- [Deploying to X](#deploying-to-x)
- [Troubleshooting](#troubleshooting)

---

## What is the Build Bridge?

`grok-build-bridge` is a small Python CLI that turns a validated YAML file
into a deployed X agent. One command drives five phases: parse, generate
(or locate) the agent source, safety-scan it, deploy, and emit a final
summary.

The whole surface fits in one sentence — but each phase is an audited
contract, not a convenience wrapper. The sections below describe the
contracts, not the conveniences.

---

## Writing a `bridge.yaml`

### Top-level keys

| Key | Type | Required | Default | Description |
| --- | --- | :---: | --- | --- |
| `version` | `string` (enum `["1.0"]`) | ✅ | — | Schema version. Pinned so v2 cannot be silently consumed by an old binary. |
| `name` | `string` (`^[a-z0-9-]{3,64}$`) | ✅ | — | Slug used for the build dir, X handle suffix, and deploy target name. |
| `description` | `string` (≤ 280 chars) | ✅ | — | One-line summary. Also the default content of the pre-deploy X-post audit. |
| `build` | `object` | ✅ | — | Where the agent source comes from. See [`build`](#build). |
| `deploy` | `object` | ✅ | — | Where the built agent goes. See [`deploy`](#deploy). |
| `agent` | `object` | ✅ | — | Model + persona. See [`agent`](#agent). |
| `safety` | `object` |  | `{}` | Runtime safety knobs. See [`safety`](#safety). |

### `build`

| Key | Type | Required | Default | Description |
| --- | --- | :---: | --- | --- |
| `source` | `enum` `grok` · `local` · `grok-build-cli` | ✅ | — | Where the code comes from. |
| `grok_prompt` | `string` | ✅ if `source ∈ {grok, grok-build-cli}` | — | Prompt handed to Grok. |
| `language` | `enum` `python` · `typescript` · `go` |  | `python` | Target language. |
| `entrypoint` | `string` |  | `main.py` / `index.ts` / `main.go` | Relative path the runtime executes. |
| `required_tools` | `array<enum x_search · web_search · code_execution>` |  | `[]` | Allow-listed xAI tools. |

**When to use each `source`:**

- `grok` — **use when** you want the bridge to be the whole source of
  truth. Prompt goes in, file comes out, everything is reproducible from
  the YAML plus `prompt_sha256` in the manifest. **Don't use when** you
  already have tested agent code you trust more than a fresh generation.
- `local` — **use when** you already own the agent code and want the
  bridge only for safety-scan + deploy. **Don't use when** you haven't
  written the code yet; `grok` is the bigger win.
- `grok-build-cli` — **use when** the ecosystem CLI is installed and you
  want its richer scaffolding. **Don't use when** your CI runners lack the
  binary — the fallback to `grok` covers it but you're paying for two
  build paths instead of one.

### `deploy`

| Key | Type | Required | Default | Description |
| --- | --- | :---: | --- | --- |
| `target` | `enum` `x` · `vercel` · `render` · `local` |  | `x` | Deploy backend. |
| `runtime` | `string` |  | `grok-install` | Runtime glue. Free-form so plugins can register new runtimes. |
| `post_to_x` | `bool` |  | `false` | When true, the agent is allowed to post autonomously. Default off so dry-runs never hit the timeline. |
| `safety_scan` | `bool` |  | `true` | Whether the phase-3 safety scan runs. Leave on unless you have a very good reason. |
| `schedule` | `string` |  | — | Cron-ish schedule string; the chosen runtime validates the dialect. |

**Target-specific behaviour:**

- `x` → calls `grok_install.runtime.deploy_to_x` when the ecosystem is
  installed; otherwise writes the payload to
  `generated/deploy_payload.json` via the fallback stub.
- `vercel` → shells out to `vercel --prod --yes`; returns the last stdout
  line as the deploy URL.
- `render` → writes a minimal `render.yaml`; deploys happen on the git-push
  side after you commit the generated dir.
- `local` → prints the right run command for the configured language.

### `agent`

| Key | Type | Required | Default | Description |
| --- | --- | :---: | --- | --- |
| `model` | `enum` `grok-4.20-0309` · `grok-4.20-multi-agent-0309` | ✅ | — | Grok model id — enum-pinned so typos fail fast. |
| `reasoning_effort` | `enum` `low` · `medium` · `high` · `xhigh` |  | `medium` | Reasoning budget dial. |
| `personality` | `string` (≤ 500 chars) |  | — | System-prompt personality snippet. |

**When to use each model:**

- `grok-4.20-0309` — **default**. Cheaper, faster, fine for the vast
  majority of single-agent jobs.
- `grok-4.20-multi-agent-0309` — **use when** the agent orchestrates
  other tools or sub-agents. **Don't use when** the task is a single
  retrieval + compose; you're paying ~3× for no extra capability.

### `safety`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `audit_before_post` | `bool` | `true` | Run a Grok-in-the-loop audit on the announcement text before any X deploy. |
| `max_tokens_per_run` | `int` `[1000, 200000]` | `8000` | Hard ceiling on tokens per bridge run. Protects the budget from runaway loops. |
| `lucas_veto_enabled` | `bool` | `false` | Enable the Lucas veto gate (Orchestra). Off by default in Bridge. |

---

## End-to-end flow

`run_bridge(yaml_path, *, dry_run, force, client)` drives the pipeline.
Each phase is tagged so any exception is reported with phase context.

### Phase 1 — Parse & validate

```python
from grok_build_bridge.parser import load_yaml

cfg = load_yaml("bridge.yaml")
# cfg is a frozen MappingProxyType; every default has been applied.
```

Parses the YAML, validates against `bridge.schema.json` (Draft 2020-12),
applies defaults, and returns a recursively frozen mapping. A schema
failure raises `BridgeConfigError` — exit code `2`.

### Phase 2 — Generate code

```python
from grok_build_bridge.builder import generate_code
from grok_build_bridge.xai_client import XAIClient

out_dir = generate_code(config, XAIClient(), yaml_dir=Path("./"))
# out_dir/main.py + out_dir/bridge.manifest.json now exist.
```

Dispatches on `build.source`. For `grok`, streams `grok-4.20-0309`,
extracts the first fenced code block, writes it to
`generated/<name>/<entrypoint>`, and emits `bridge.manifest.json` with
`name`, `source`, `model`, `prompt_sha256`, `generated_at`,
`token_usage_estimate`, and the file list.

### Phase 3 — Safety scan

```python
from grok_build_bridge.safety import scan_generated_code

report = scan_generated_code(code_text, language="python", config=cfg)
if not report.safe:
    for issue in report.issues:
        print("•", issue)
```

Static regex sweep ∪ JSON-mode Grok audit ↦ one
[`SafetyReport`](../grok_build_bridge/safety.py). A `safe=False` report
aborts phase 4 unless you passed `--force`.

### Phase 4 — Deploy

```python
from grok_build_bridge.deploy import deploy_to_target

url = deploy_to_target(out_dir, config, client=XAIClient())
```

Dispatches on `deploy.target`. For `x`, the announcement text is audited
with `audit_x_post` before the deploy fires. A failing audit raises
`BridgeSafetyError` (exit code `4`) unless the gates are turned off.

### Phase 5 — Summary

A green Rich panel titled "✅ Bridge complete" wrapping a two-column
table of `success`, `generated_path`, `safety`, `deploy_target`,
`deploy_url`, `duration`, and `tokens (est.)`.

---

## Safety guarantees

Two independent layers. Either one can block a run; both must pass for
Bridge to consider the agent safe.

### Layer 1 — Static sweep

Compiled regex catalog in [`_patterns.py`](../grok_build_bridge/_patterns.py).
Every finding has a slug prefix so consumers can key on the class of issue:

- `hardcoded-secret` — AWS / xAI / OpenAI / GitHub token shapes.
- `unsafe-eval` — `eval(` / `exec(` calls.
- `infinite-loop` — `while True:` / `while (true)` with no visible break.
- `shell-call` — `subprocess(..., shell=True)` / `os.system` / `os.popen`.
- `no-timeout` — `requests.*(...)` without a `timeout=` kwarg.
- `unsafe-deserialization` — `pickle.load` / `yaml.load` without `SafeLoader`.

For non-Python languages (`typescript`, `go`) only the secret checks run —
the runtime-construct rules are Python-shaped and would produce false
positives elsewhere.

### Layer 2 — Grok-in-the-loop audit

`grok-4.20-0309` is prompted for a strict JSON answer about X API abuse,
rate-limit risk, misinformation risk, PII exposure, and infinite-loop
risk. Pinned to the cheaper model because the audit runs on every bridge
invocation — tripling the cost for a safety check you run this often is
not a good trade. The system prompt establishes the reviewer role; the
user prompt carries the artefact under review so Grok does not confuse
code comments for instructions.

Both layers' findings merge into one `SafetyReport` with a combined
`score` in `[0, 1]`, a list of `issues`, and a list of `recommendations`.
The report also carries an `estimated_cost_usd` so you can see the audit
cost in the same breath as the verdict.

---

## Deploying to X

The `x` target is the happy path. Its internal flow:

1. `_announcement_for(config)` — pulls the text to audit. v0.1 policy: use
   the `description` field (schema-capped to 280 chars so it fits in one
   post). A future revision will let you pin `deploy.post_content`.
2. `audit_x_post(content, config, client)` — runs the post-audit layer.
3. If the report is unsafe **and** `audit_before_post` or
   `lucas_veto_enabled` is set, raise `BridgeSafetyError` — deploy is
   blocked. Otherwise proceed.
4. Read `bridge.manifest.json` and build the payload (`name`,
   `description`, `agent`, `deploy`, `generated_dir`, `manifest`).
5. Hand off to `grok_install.runtime.deploy_to_x` when available; fall
   back to the local stub otherwise.

To short-circuit the audit (e.g. during a migration), set
`safety.audit_before_post: false` in the YAML. To bypass a failing
audit on a specific run, pass `--force` to `grok-build-bridge run`.

---

## Troubleshooting

Ten failure modes and their fixes. Every error message the bridge emits
includes a `suggestion:` field — check that first.

### 1. `missing xAI API key`

- **Cause:** `XAI_API_KEY` is not set in the environment.
- **Fix:** `export XAI_API_KEY=sk-...` or use a `.env` file. The bridge
  degrades to a static-only safety scan when the key is missing and no
  client is injected, so dry-runs work in CI without a key.

### 2. `'<key>' is a required property`

- **Cause:** Your YAML is missing a required field.
- **Fix:** Run `grok-build-bridge validate <file.yaml>` — the Rich panel
  names the missing key. The schema lives at
  [`grok_build_bridge/schema/bridge.schema.json`](../grok_build_bridge/schema/bridge.schema.json).

### 3. `name: 'Bad Name!' does not match '^[a-z0-9-]{3,64}$'`

- **Cause:** `name` must be slug-safe for X handles, Vercel / Render
  project names, and DNS.
- **Fix:** `name: my-good-name` (lowercase, digits, and hyphens only).

### 4. `unknown model 'grok-4'`

- **Cause:** Bridge pins `agent.model` to an enum so typos fail fast.
- **Fix:** Use one of `grok-4.20-0309` or `grok-4.20-multi-agent-0309`.

### 5. `build.source is 'grok' but build.grok_prompt is empty`

- **Cause:** Grok-backed source modes require a prompt.
- **Fix:** Add a `grok_prompt:` block. See the certified templates in
  [`grok_build_bridge/templates/`](../grok_build_bridge/templates) for
  examples of production-grade prompts.

### 6. `local source requires <file> to exist`

- **Cause:** `build.source: local` means you ship the code yourself.
- **Fix:** Place the file at `generated/<name>/<entrypoint>` or next to
  the YAML at `<yaml_dir>/<name>/<entrypoint>` / `<yaml_dir>/<entrypoint>`.

### 7. `safety auditor returned non-JSON`

- **Cause:** Grok sometimes returns prose when asked for JSON.
- **Fix:** Re-run. If the error persists, file a bug — the audit prompt
  anchors hard on "Return ONLY a JSON object..." and drift suggests a
  model or SDK update has shifted behaviour.

### 8. `xAI call failed after 3 attempts`

- **Cause:** Three consecutive retry-able failures (rate limit, API
  connection, timeout).
- **Fix:** Wait a minute, verify your key at https://console.x.ai, or run
  with `--dry-run` to skip the LLM-dependent phases.

### 9. `safety scan blocked the deploy`

- **Cause:** Phase 3 reported `safe=False`.
- **Fix:** Read the bulleted issues above the red panel. Either fix the
  generated code (tighten the `grok_prompt`) or, if you understand the
  risk, re-run with `--force`.

### 10. `vercel deploy failed (exit 1)`

- **Cause:** Vercel CLI did not succeed.
- **Fix:** Run `vercel login` from the same shell and retry. If the CLI
  is not installed at all, Bridge prints a "vercel CLI not found" line
  and returns the placeholder `vercel://pending/<name>` URL — no hard
  failure.
