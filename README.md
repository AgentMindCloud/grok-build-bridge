<!-- NEON / CYBERPUNK REPO TEMPLATE · GROK-BUILD-BRIDGE -->

<p align="center">
  <img
    src="https://capsule-render.vercel.app/api?type=waving&height=230&color=0:00E5FF,50:7C3AED,100:FF4FD8&text=grok-build-bridge&fontSize=52&fontColor=EAF8FF&fontAlign=50&fontAlignY=38&desc=One%20YAML%20%E2%86%92%20Grok%20Builds%20It%20%E2%86%92%20Safely%20Live%20on%20X&descAlignY=62&descSize=17"
    width="100%"
    alt="header"
  />
</p>

<h1 align="center">⚡ grok-build-bridge</h1>

<p align="center">
  <b>The last mile from "Grok generated my code" to "agent is live on X posting every 6 hours."</b><br/>
  One YAML. Codegen. Safety audit. Deploy. Zero glue.
</p>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Space+Grotesk&weight=700&size=22&pause=1000&color=00E5FF&center=true&vCenter=true&width=900&lines=Grok+4.20+Generates+the+Agent+from+YAML;Two-Layer+Safety+%E2%80%94+Static+%2B+Grok+Audit;Deploy+to+X+%C2%B7+Vercel+%C2%B7+Render+%C2%B7+Local;Lucas+Veto+Hook+%E2%80%94+Orchestra+Ready" alt="typing" />
</p>

<p align="center">
  <a href="https://pypi.org/project/grok-build-bridge/"><img src="https://img.shields.io/pypi/v/grok-build-bridge.svg?style=for-the-badge&color=00E5FF&labelColor=0A0D14" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/Apache%202.0-7C3AED?style=for-the-badge&logoColor=FFFFFF&labelColor=0A0D14" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python%203.10+-FF4FD8?style=for-the-badge&logo=python&logoColor=FFFFFF&labelColor=0A0D14" /></a>
  <a href="https://x.ai"><img src="https://img.shields.io/badge/Grok%204.20-00D5FF?style=for-the-badge&logoColor=001018&labelColor=0A0D14" /></a>
  <a href="https://x.ai"><img src="https://img.shields.io/badge/xAI%20Aligned-9D4EDD?style=for-the-badge&logoColor=FFFFFF&labelColor=0A0D14" /></a>
  <img src="https://img.shields.io/badge/Coverage%2085%25-5EF2FF?style=for-the-badge&logoColor=001018&labelColor=0A0D14" />
</p>

<p align="center">
  <img src="docs/assets/bridge-demo.gif" alt="grok-build-bridge demo — one YAML, one command, deployed X agent" width="720" />
</p>

<p align="center">
  <a href="#-60-second-quick-start"><b>🚀 Quick Start</b></a> ·
  <a href="#-templates"><b>📚 Templates</b></a> ·
  <a href="#-safety"><b>🛡️ Safety</b></a> ·
  <a href="#-roadmap"><b>🗺️ Roadmap</b></a>
</p>

---

## ✦ Why Bridge Exists

<table>
  <tr>
    <td width="33%">
      <h3>🎯 Close the Last Mile</h3>
      <p>Grok 4.20 can already write the agent — somebody just has to ship it. Bridge closes the gap between "Grok generated my code" and "agent is live on X posting every 6 hours."</p>
    </td>
    <td width="33%">
      <h3>🛡️ Safety Isn't Optional</h3>
      <p>Every run statically scans generated code for secrets / shell injection / infinite loops, and runs a second Grok-in-the-loop audit before the agent touches the public timeline.</p>
    </td>
    <td width="33%">
      <h3>⚡ One YAML, Zero Glue</h3>
      <p>You describe the agent once — source mode, tools, schedule, safety limits, deploy target. The CLI runs the rest. No Terraform, no Procfile, no per-host deploy scripts.</p>
    </td>
  </tr>
</table>

## ✦ 60-Second Quick Start

```bash
# 1. Install (Python 3.10+)
pip install grok-build-bridge

# 2. Scaffold a ready-to-run template
grok-build-bridge init x-trend-analyzer
#   + bridge.yaml

# 3. Dry-run the full pipeline — no API keys needed for this step
grok-build-bridge run bridge.yaml --dry-run

# 4. Set your key and ship it for real
export XAI_API_KEY=sk-...
export X_BEARER_TOKEN=...
grok-build-bridge run bridge.yaml
```

Five phase headers scroll past, a green **✅ Bridge complete** panel prints, and your agent is live.

## ✦ The YAML

One file. Every knob. Nothing implicit:

```yaml
version: "1.0"
name: x-trend-analyzer
description: Every 6 hours, summarise the top 5 technical trends on X with primary-source citations.

build:
  source: grok                   # stream the implementation from Grok
  language: python
  entrypoint: main.py
  required_tools:
    - x_search
    - web_search
  grok_prompt: |
    Generate ONE Python 3.11 file that polls x_search for trending AI
    topics, verifies each with web_search, and publishes one thread...

deploy:
  target: x                      # hand off to grok-install's deploy_to_x
  post_to_x: true
  schedule: "0 */6 * * *"        # every 6 hours
  safety_scan: true

agent:
  model: grok-4.20-0309          # pinned; enum-validated
  reasoning_effort: medium
  personality: Neutral, factual, citation-first.

safety:
  audit_before_post: true        # Grok audits the post before it fires
  max_tokens_per_run: 18000      # hard ceiling — runaway loops can't burn your budget
  lucas_veto_enabled: false      # Orchestra enables this; Bridge defaults off
```

VS Code autocompletes every key — see [`docs/vscode-integration.md`](docs/vscode-integration.md).

## ✦ The Five Phases

```mermaid
flowchart LR
    A["📄 phase 1<br/>parse · validate YAML"] --> B["🎯 phase 2<br/>generate code"]
    B --> C["🛡️ phase 3<br/>safety scan"]
    C -->|safe=false| X["🚫 block deploy<br/>unless --force"]
    C -->|safe=true| D["🚀 phase 4<br/>deploy"]
    D --> E["✅ phase 5<br/>BridgeResult"]
```

<table>
  <tr>
    <td width="50%">
      <h3>📄 Phase 1 · Parse</h3>
      <p>Strict Draft 2020-12 schema, defaults filled, result frozen. No guessing.</p>
    </td>
    <td width="50%">
      <h3>🎯 Phase 2 · Generate</h3>
      <p>Streams <code>grok-4.20-0309</code> via official <code>xai-sdk</code>. Extracts a fenced code block. Writes <code>bridge.manifest.json</code> (name · model · prompt sha-256 · token estimate · file list).</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🛡️ Phase 3 · Safety</h3>
      <p>Regex static sweep + JSON-mode Grok audit, merged into one <code>SafetyReport</code>.</p>
    </td>
    <td>
      <h3>🚀 Phase 4 · Deploy</h3>
      <p>Dispatches on <code>deploy.target</code>: <code>x</code> · <code>vercel</code> · <code>render</code> · <code>local</code>. X-bound posts get a pre-flight <code>audit_x_post</code>.</p>
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <h3>✅ Phase 5 · Summary</h3>
      <p>Green Rich panel: generated path · safety verdict · deploy URL · duration · token estimate.</p>
    </td>
  </tr>
</table>

**Resilience:** transient xAI failures (rate limits, connection resets, timeouts) are retried under tenacity — 3 attempts, exponential backoff clamped to 2–16 s. `ToolExecutionError` retries once with tools disabled before surfacing.

## ✦ CLI

Five commands. Every failure path prints a branded Rich panel with a "What to try next" list and exits with a typed code so scripts can react.

| Command | What it does |
| --- | --- |
| `grok-build-bridge run <file.yaml>` | Full pipeline. Flags: `--dry-run`, `--force` (bypass safety block), `--verbose/-v`. |
| `grok-build-bridge validate <file.yaml>` | Parse, schema-validate, apply defaults, and pretty-print the resolved config — no network. |
| `grok-build-bridge templates` | List bundled templates with description, required env, estimated tokens, categories. |
| `grok-build-bridge init <slug>` | Copy a bundled template to `--out/-o` (default: cwd). `--force` skips the overwrite prompt. |
| `grok-build-bridge version` | Print grok-build-bridge / xai-sdk / python versions. |

**Global flags:** `--version/-V` · `--no-color` (also honours `NO_COLOR`).

**Exit codes:** `2` config error · `3` runtime error · `4` safety block.

### Environment

| Var | Used for |
| --- | --- |
| `XAI_API_KEY` | Every Grok call (build + safety + X-post audit). |
| `X_BEARER_TOKEN` | Deploys with `deploy.target: x`. |
| `GROK_INSTALL_HOME` | Optional — path to a local `grok-install-ecosystem` checkout for the `deploy_to_x` bridge. |

See [`.env.example`](.env.example).

## ✦ Deploy Targets

<p align="center">
  <img src="https://img.shields.io/badge/target%3A%20x-00E5FF?style=for-the-badge&logo=x&logoColor=001018&labelColor=0A0D14" />
  <img src="https://img.shields.io/badge/target%3A%20vercel-7C3AED?style=for-the-badge&logo=vercel&logoColor=FFFFFF&labelColor=0A0D14" />
  <img src="https://img.shields.io/badge/target%3A%20render-FF4FD8?style=for-the-badge&logoColor=FFFFFF&labelColor=0A0D14" />
  <img src="https://img.shields.io/badge/target%3A%20local-00D5FF?style=for-the-badge&logoColor=001018&labelColor=0A0D14" />
</p>

- **`x`** — via `grok_install.runtime.deploy_to_x`, or a dry-run stub that writes `generated/deploy_payload.json` when the ecosystem package is absent.
- **`vercel`** — shells out to `vercel --prod --yes`.
- **`render`** — writes a minimal `render.yaml`.
- **`local`** — prints the run command. Good for CI smoke tests.

## ✦ Templates

`grok-build-bridge templates` lists the six certified templates that ship in the wheel:

| Slug | What it does | Source mode | Required env |
| --- | --- | --- | --- |
| [`hello-bot`](grok_build_bridge/templates/hello-bot/bridge.yaml) | Smallest local-source agent — greets stdout and exits. Use it as the first bridge smoke test. | `local` | — |
| [`x-trend-analyzer`](grok_build_bridge/templates/x-trend-analyzer.yaml) | Every 6 hours → one thread summarising the top 5 trends with primary-source citations. | `grok` | `XAI_API_KEY`, `X_BEARER_TOKEN` |
| [`truthseeker-daily`](grok_build_bridge/templates/truthseeker-daily.yaml) | Daily fact-check of the 3 most-discussed threads in a domain, with a calibration note. | `grok` | `XAI_API_KEY`, `X_BEARER_TOKEN` |
| [`code-explainer-bot`](grok_build_bridge/templates/code-explainer-bot.yaml) | Point at a Python repo via `$TARGET_REPO` → plain-English explainer thread. | `local` | `TARGET_REPO`, `XAI_API_KEY`, `X_BEARER_TOKEN` |
| [`grok-build-coding-agent`](grok_build_bridge/templates/grok-build-coding-agent.yaml) | Tiny TypeScript CLI via the `grok-build-cli` → `grok` fallback chain. | `grok-build-cli` | `XAI_API_KEY` |
| [`research-thread-weekly`](grok_build_bridge/templates/research-thread-weekly.yaml) | Weekly deep-research: 5 parallel queries + web verification → one authoritative thread. | `grok` | `XAI_API_KEY`, `X_BEARER_TOKEN` |

Scaffold any with `grok-build-bridge init <slug>`. Standalone end-to-end example: [`examples/hello.yaml`](examples/hello.yaml) + [`examples/hello-bridge/main.py`](examples/hello-bridge/main.py).

## ✦ Safety

Two layers between Grok-generated code and the public timeline.

<table>
  <tr>
    <td width="50%">
      <h3>🔎 Layer 1 · Static Sweep</h3>
      <p>Compiled regex catalog flags hardcoded AWS / xAI / OpenAI / GitHub keys, <code>eval()</code> / <code>exec()</code>, unbounded <code>while True</code>, <code>subprocess(..., shell=True)</code>, <code>os.system</code>, <code>requests</code> calls without <code>timeout=</code>, and <code>pickle.load</code> / <code>yaml.load</code> without <code>SafeLoader</code>. Every finding carries a short slug (<code>shell-call:</code>, <code>hardcoded-secret:</code>, <code>no-timeout:</code>, …) that downstream tooling can key on.</p>
    </td>
    <td width="50%">
      <h3>🤖 Layer 2 · Grok-in-the-Loop Audit</h3>
      <p><code>grok-4.20-0309</code> reviews the produced file in strict JSON mode for X API abuse, rate-limit risk, misinformation risk, PII exposure, and infinite-loop risk. Layers merge into a frozen <a href="grok_build_bridge/safety.py"><code>SafetyReport</code></a>. A failing scan blocks deploy unless you pass <code>--force</code>.</p>
    </td>
  </tr>
</table>

### 🎭 Lucas veto (preview)

Bridge leaves `safety.lucas_veto_enabled` off by default. The flag is wired for [**Orchestra**](https://github.com/AgentMindCloud/grok-agent-orchestra) — the multi-agent sibling project — where a named Lucas agent holds a veto on anything that reaches X. Compose via `grok-orchestra combined`.

## ✦ xAI Alignment

Bridge is **100% additive to xAI's mission** — it exists to make more people ship more Grok 4.20 agents, safely.

Every model call goes through the official [`xai-sdk`](https://github.com/xai-org/xai-sdk-python) using enum-pinned model ids (`grok-4.20-0309` / `grok-4.20-multi-agent-0309`) — no fallbacks, no wrappers that could drift from xAI's intended behaviour. The only deploy glue Bridge touches is the companion [`grok-install-ecosystem`](https://github.com/AgentMindCloud/grok-install-ecosystem) — an Apache-2.0 community layer that xAI can adopt, fork, or replace at any time.

## ✦ Roadmap

<table>
  <tr>
    <td width="50%">
      <h3>🎭 Week 1 · Orchestra Teaser</h3>
      <p>Multi-agent companion project drops. Named Lucas veto becomes the first external user of Bridge's <code>lucas_veto_enabled</code> flag. <b>✅ Shipped</b> — see <a href="https://github.com/AgentMindCloud/grok-agent-orchestra">grok-agent-orchestra</a>.</p>
    </td>
    <td width="50%">
      <h3>📊 Week 2 · X Observability</h3>
      <p>Per-agent dashboards (posts/day, audit-blocks, token burn) rendered to the CLI and emitted as Prometheus on request.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🤖 Week 3 · Official GitHub Action</h3>
      <p>Replace the <code>grok_install.runtime.deploy_to_x</code> fallback stub with a maintained GitHub Action.</p>
    </td>
    <td>
      <h3>⚙️ Week 4 · Batch Mode</h3>
      <p><code>grok-build-bridge run *.bridge.yaml</code> for operators who manage ten agents at once.</p>
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <h3>🚀 Week 4 · v0.2.0 on PyPI</h3>
      <p>Tagged release via the trusted-publishing pipeline already live on <code>main</code>.</p>
    </td>
  </tr>
</table>

Full plan: [`ROADMAP.md`](ROADMAP.md).

## ✦ Contributing

Dev install, branching, commit style, and PR checklist live in [`CONTRIBUTING.md`](CONTRIBUTING.md). In short:

```bash
git clone https://github.com/AgentMindCloud/grok-build-bridge.git
cd grok-build-bridge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy grok_build_bridge && pytest
```

## ✦ Sibling Repos

<table>
  <tr>
    <td width="33%">
      <h3>🎭 grok-agent-orchestra</h3>
      <p>The multi-agent layer — debate + Lucas veto — that composes with Bridge via <code>grok-orchestra combined</code>.</p>
      <a href="https://github.com/agentmindcloud/grok-agent-orchestra">Repository →</a>
    </td>
    <td width="33%">
      <h3>📦 grok-install</h3>
      <p>The universal YAML spec for declarative agents.</p>
      <a href="https://github.com/agentmindcloud/grok-install">Repository →</a>
    </td>
    <td width="33%">
      <h3>⚙️ grok-install-cli</h3>
      <p>The CLI Bridge hands off to on <code>deploy.target: x</code>.</p>
      <a href="https://github.com/agentmindcloud/grok-install-cli">Repository →</a>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🌟 awesome-grok-agents</h3>
      <p>10 certified templates — complementary to Bridge's 6 codegen templates.</p>
      <a href="https://github.com/agentmindcloud/awesome-grok-agents">Repository →</a>
    </td>
    <td>
      <h3>📐 grok-yaml-standards</h3>
      <p>12 modular YAML extensions that Bridge-generated agents can reference.</p>
      <a href="https://github.com/agentmindcloud/grok-yaml-standards">Repository →</a>
    </td>
    <td>
      <h3>🛒 grok-agents-marketplace</h3>
      <p>The live marketplace at <a href="https://grokagents.dev">grokagents.dev</a>.</p>
      <a href="https://github.com/agentmindcloud/grok-agents-marketplace">Repository →</a>
    </td>
  </tr>
</table>

## ✦ Connect

<p align="center">
  <a href="https://github.com/agentmindcloud">
    <img src="https://img.shields.io/badge/GitHub-00E5FF?style=for-the-badge&logo=github&logoColor=001018&labelColor=0A0D14" />
  </a>
  <a href="https://x.com/JanSol0s">
    <img src="https://img.shields.io/badge/X-7C3AED?style=for-the-badge&logo=x&logoColor=FFFFFF&labelColor=0A0D14" />
  </a>
  <a href="https://grokagents.dev">
    <img src="https://img.shields.io/badge/grokagents.dev-FF4FD8?style=for-the-badge&logoColor=FFFFFF&labelColor=0A0D14" />
  </a>
</p>

## ✦ License

Apache 2.0 — see [`LICENSE`](LICENSE). Copyright © 2026 Jan Solo / AgentMindCloud.

## ✦ Credits

- The **xAI team** for Grok 4.20 and the official `xai-sdk` Python client.
- The **`grok-install-ecosystem`** community for the `deploy_to_x` glue Bridge builds on.
- Every early user who filed a good bug report. Threads are a finite resource — thanks for spending one on us.

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=120&section=footer&color=0:00E5FF,50:7C3AED,100:FF4FD8" width="100%" />
</p>
