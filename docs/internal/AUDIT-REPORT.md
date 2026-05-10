# Audit Report: grok-build-bridge

**Date:** 2026-05-07
**Auditor:** Claude Code
**Org:** AgentMindCloud
**Ecosystem Role:** YAML-driven build pipeline that takes a Grok-generated agent spec, calls `xai-sdk` to materialise code, runs a regex+LLM dual safety scan, and deploys to one of six targets (X, Vercel, Render, Railway, Fly.io, local) — the "deploy automation" half of the xAI/Grok/X-native stack.

---

## 1. Snapshot

- **Stars / forks / open issues:** unknown — GitHub MCP token expired during audit; `gh` CLI not available
- **Last commit:** `f9f838d` 2026-04-29 — "feat: Wave 3 — link, fork, publish --upload (multi-agent pull)" (8 days stale at audit time)
- **Primary language(s):** Python 3.10/3.11/3.12 (core); HTML/CSS/JS (landing page, bridge.live)
- **Total LOC:** ~14,300 — Python 8,602 (12 modules + 11 tests), HTML 1,446, Markdown 2,291, YAML 1,077, JSON 536, CSS 341
- **Dependencies health:** lower-bound-only pinning (`xai-sdk>=1.0`, `httpx>=0.27`, etc.); no vulnerabilities surfaced but the in-CI `pip-audit` is silently neutered (see Critical findings); `pytest-asyncio` documented in CONTRIBUTING.md but absent from `[dev]` extras; `requirements.txt` exists alongside `pyproject.toml` as a drift vector
- **CI status:** workflows present and structured (`ci.yml`, `release.yml`, `bridge-pr.example.yml`, composite action at `.github/actions/bridge/action.yml`); 6 CI jobs (lint, test 3x2 matrix, schema-check, safety-scan, docs-link-check, build); last-run state unknown (MCP unavailable)
- **License:** Apache-2.0, present at repo root (`LICENSE`)
- **Required files present:** README ✓, LICENSE ✓, CHANGELOG ✓ (stale — 0.1.0 only), CONTRIBUTING ✓, .gitignore ✓, CODE_OF_CONDUCT ✗, SECURITY ✗

---

## 2. File-by-File Findings

### Critical

- `assets/buildbridge.gif:1` — File is a 49-byte ASCII text blob (`![Build Bridge Upgrade] (assets/buildbridge.gif)`), not an actual GIF; every renderer downstream gets a broken image — **Severity:** Critical
- `CHANGELOG.md:6` — `[assets/buildbridge.gif]` is malformed Markdown image syntax (missing `!` and parens); even with a real GIF this would not render — **Severity:** Critical
- `.github/workflows/ci.yml:169` — `pip-audit --strict --ignore-vuln GHSA-0000-0000-0000 || true` silently swallows every CVE; the safety-scan job appears in CI but cannot block on a real vulnerability — **Severity:** Critical
- `bridge_live/inspector.py:51` — `tmp = Path("/tmp") / f"bridge-live-{sha_for(yaml_text)}.yaml"` hardcodes `/tmp` (Linux/macOS only) and uses content-derived filenames; two concurrent identical-YAML requests race on the same file with `unlink()` in `finally` — **Severity:** Critical
- `grok_build_bridge/publish.py:106-114` — `_load_schema` resolves `marketplace/manifest.schema.json` via repo-relative path; that directory is OUTSIDE the wheel package per `pyproject.toml:[tool.hatch.build.targets.wheel]`, so `publish` will fail with `BridgeConfigError` for every PyPI installer — **Severity:** Critical
- `docs/index.html:259-419, 1051-1139` — Hardcoded fake telemetry rendered as live status (`1,284 active agents`, `99.7% safety pass rate`, animated stream of fake handles `@nora`/`@kenji`/etc.); disclaimer at line 418 is 12px muted text; for a safety-positioned product this is the single most credibility-eroding piece of content in the repo — **Severity:** Critical
- `launch/x-thread.md:98` — Inline `@grok @elonmusk @xai` (no backticks) inside a markdown blockquote; on GitHub these auto-link to user `grok` (Sterling Hamilton) rather than the X handles — **Severity:** Critical
- `README.md:14, 109, 325, 481` — README directs users to `pip install grok-build-bridge`; the package is NOT on PyPI (`README.md:32` itself shows a "PyPI Pending" badge); install instructions break for every reader today — **Severity:** Critical

### High

- `examples/orchestra-bridge/bridge.yaml:111` — Comment promises `lucas_veto_enabled: true # Honours ./out/veto-report.json verdict`; no code in `grok_build_bridge/` reads `veto-report.json` — `safety.lucas_veto_enabled` is only an OR-gate alongside `audit_before_post` in `deploy.py:96-128` — documented contract diverges from implementation — **Severity:** High
- `vscode/schemas/bridge.schema.json:128` — `deploy.target` enum is `["x","vercel","render","local"]` (4 targets); main schema at `grok_build_bridge/schema/bridge.schema.json:72` has 6 (adds `railway`,`flyio`); also Draft-07 vs main's Draft 2020-12; CONTRIBUTING.md:64 explicitly demands sync — **Severity:** High
- `vscode/snippets/bridge.code-snippets:17` — Identical 4-target drift in snippet choice list — **Severity:** High
- `docs/index.html:714` — Phase 4 card lists `target: x · vercel · render · local`; out of sync with README's six-target story — **Severity:** High
- `CHANGELOG.md:14-27` — Only `[0.1.0]` entry exists, but Wave 0 (doctor), bridge-live, dev hot-reload, marketplace publish + `--upload`, link/fork, GitHub Action, Railway/Fly.io targets have all shipped; `release.yml:105-126` extracts release notes from this CHANGELOG, so every future tag will publish empty notes — **Severity:** High
- `marketplace/README.md:71-75` — "Not yet wired: Upload endpoint — `grok-build-bridge publish --upload` will exist once the registry API ships"; contradicts shipped code at `cli.py:982-990` and `publish.py:438-481` — **Severity:** High
- `ROADMAP.md:117-122` — "Week 7 — `publish --upload`" listed as unchecked future work despite being shipped — **Severity:** High
- `README.md:424` — "The CLI does not upload anywhere yet. `--upload` lands in v0.3.0…" contradicts CLI table at `README.md:268` and the shipped code; internal README inconsistency — **Severity:** High
- `CONTRIBUTING.md:18` — Lists `pytest-asyncio` as an installed dev dep, but it is not in `pyproject.toml:38-49`; following the docs leaves contributors without a dep that's also unused (no async tests) — **Severity:** High
- `launch/email-sales-xai.md:15` and `launch/email-media-xai.md:15-17` — Both pitch emails claim "five certified templates"; INDEX.yaml ships eight (also matched in README and bridge_live); media email also contradicts `README.md:229` claim of "~40 seconds for a typical agent" with "the whole pipeline runs in ~5 seconds" — **Severity:** High
- `launch/x-thread.md:7` — Tweet 1 attaches `docs/assets/bridge-demo.gif`; `docs/assets/` directory does not exist; the only "GIF" is the 49-byte stub at `assets/buildbridge.gif`; thread cannot be posted as written — **Severity:** High
- `README.md:37` — Hardcoded "Coverage 85%" badge; that's the CI floor (`ci.yml:80`), not the measured coverage — misleading even if technically the floor — **Severity:** High
- `README.md:19` — "Lucas Certified" badge is invented branding with no certification mechanism defined anywhere in this repo or any sibling visible from here — **Severity:** High
- `CHANGELOG.md:1-7` — Casual preface "Fresh from the oven, v1.0 brand new version!!" sits above the Keep-a-Changelog block while `__version__ = "0.1.0"`; confused versioning narrative — **Severity:** High
- `pyproject.toml:8` — Description says "multi-target deploy (X / Vercel / Render / local)"; Railway and Fly.io were added but description was never updated — **Severity:** High

### Medium

- `grok_build_bridge/runtime.py:297-308` — `async def bridge(...)` is dead code — docstring calls it back-compat for "session-1 scaffolding" but no callers, no test, not re-exported — **Severity:** Medium
- `grok_build_bridge/__init__.py:30-51` — `__all__` lists submodule names (`builder`, `cli`, `deploy`, `parser`, `runtime`, `safety`, `xai_client`) that are NOT bound at module top level; `from grok_build_bridge import *` will throw AttributeError — **Severity:** Medium
- `grok_build_bridge/safety.py:149-151` — `_USD_PER_1K_INPUT = 0.005`, `_USD_PER_1K_OUTPUT = 0.015` hardcoded with no version pin or doc reference; cost reports will silently drift as xAI pricing changes — **Severity:** Medium
- `grok_build_bridge/safety.py:106` and `grok_build_bridge/builder.py:106` — `int(generated_chars / 4)` heuristic for token count is reused for cost without disclosure that input vs output tokens differ — **Severity:** Medium
- `grok_build_bridge/deploy.py:188-194, 232-239, 267-274` — Vercel/Railway/Fly subprocess calls use `capture_output=True, text=True`; user sees nothing for long deploys until completion — **Severity:** Medium
- `grok_build_bridge/deploy.py:294-314` — `_render_yaml_body` builds YAML by f-string concatenation; `_fly_toml_body` does the same for TOML; will break on YAML/TOML special chars in `name`/cmd; should use `yaml.safe_dump` — **Severity:** Medium
- `grok_build_bridge/deploy.py:144-147` — `_GROK_INSTALL_AVAILABLE: Final = False` annotated `Final` but tests `monkeypatch.setattr(...)` it; the typing annotation is lying — **Severity:** Medium
- `grok_build_bridge/cli.py:301-322` — `dev` watcher polls `time.sleep(interval)` with `min=0.1`; worst case ~10 stat() polls/sec on every file; no upper bound on watched files — **Severity:** Medium
- `.github/workflows/ci.yml:78-86` — `codecov/codecov-action@v4` is version-pinned, not SHA-pinned; Codecov has had supply-chain incidents — **Severity:** Medium
- `.github/workflows/release.yml:81` — `pypa/gh-action-pypi-publish@release/v1` is a moving tag; PyPI publishing should be SHA-pinned per OpenSSF guidance — **Severity:** Medium
- `.github/actions/bridge/action.yml:109-128` — `cat`s `validate.txt`/`dry-run.txt` into PR comment markdown with no escaping; bounded by `<details>`+code fences but a malicious bridge.yaml could produce mangled rendering — **Severity:** Medium
- `bridge_live/Dockerfile:6-44` — Runs as root; main `Dockerfile` correctly uses non-root UID 10001 + tini; bridge.live image inconsistent with project's documented security posture — **Severity:** Medium
- `bridge_live/store.py:24` — `_DEFAULT_HOME = Path(".passports")` is cwd-relative; bare `uvicorn` from different dirs fragments the SHA store (Docker is safe via env override) — **Severity:** Medium
- `grok_build_bridge/deploy.py:43-45` and `grok_build_bridge/builder.py:73-77` — `Path("generated") / "deploy_payload.json"` and `_resolve_generated_dir` default to `Path.cwd()`; running from a different directory writes outputs to the wrong place — **Severity:** Medium
- `examples/orchestra-bridge/README.md:50` — Tells users `pip install grok-build-bridge grok-agent-orchestra`; neither is on PyPI yet — **Severity:** Medium
- `launch/seven-day-shipping-plan.md` — Day 1 says "Land a v0.1.0 tag only after every job is green"; today is 2026-05-07, last commit 2026-04-29, no git tags exist; plan never started — **Severity:** Medium
- `docs/vscode-integration.md:50` — Promises a screenshot GIF in `docs/assets/` "once the extension packaging PR lands"; PR not shipped — **Severity:** Medium
- `README.md:585` — "Documentation site coming soon" but `docs/index.html` exists at landing-page quality and is NOT linked from the README; orphan growth risk — **Severity:** Medium
- `grok_build_bridge/parser.py:99-103` — Schema is read on EVERY `load_yaml` call to "stay fresh in tests"; not free with a 4 KB JSON + jsonschema compilation — **Severity:** Medium
- `Dockerfile:111-118` — `EXPOSE 8000` reserved for "upcoming Typer-based status UI (roadmap Phase 4)"; nothing binds 8000 in the main image; phantom port — **Severity:** Medium

### Low

- `grok_build_bridge/parser.py:240-265` — `load_yaml` calls `err.render()` (writes to stderr) AND raises; CLI's `_handle_and_exit` then renders again via `_render_error_panel`; every config error is printed twice — **Severity:** Low
- `grok_build_bridge/_patterns.py:28-31` — AWS access-key prefix list misses `ABIA` (newer service-role keys) — **Severity:** Low
- `grok_build_bridge/_patterns.py:81-83` — `_REQUESTS_NO_TIMEOUT` regex is single-line; multi-line `requests.get(...\n  timeout=...)` evades it (false negative) — **Severity:** Low
- `grok_build_bridge/templates/code-explainer-bot.yaml`, `truthseeker-daily.yaml`, `flyio-edge-bot.yaml` — Multiple templates advertise inline costs ("~$0.10 per invocation"); will drift with xAI pricing — **Severity:** Low
- `Dockerfile:69` — Healthcheck `grok-build-bridge version` imports `xai_sdk` (`cli.py:1257`); can mask real dependency-chain failures — **Severity:** Low
- `bridge_live/README.md:138` — "the acquisition surface" / "the growth plan" jargon reads odd for an OSS reader — **Severity:** Low
- `docker-compose.yml:79-91` — `bridge` service `command: ["--help"]` exits immediately, making `up` unhelpful (acknowledged in comment) — **Severity:** Low

### Nit

- `grok_build_bridge/_banner.py:18-25` — 6-line ASCII banner wider than 120 cols; wraps on default terminals — **Severity:** Nit
- `grok_build_bridge/cli.py:301-302` — `import time` inside `dev_cmd` rather than at module top; style inconsistency — **Severity:** Nit
- `README.md:32` — "PyPI Pending" badge redundant with the live PyPI badge two lines above (which will say "not found") — **Severity:** Nit
- `docs/index.html:147,192` — Hardcoded `v0.1.0` label twice; manual bump per release — **Severity:** Nit
- `grok_build_bridge/templates/grok-build-coding-agent.yaml:26` — Description capitalization inconsistent ("deploy target is local") — **Severity:** Nit
- `README.md:573` — "Copyright © 2026 Jan Solo / AgentMindCloud" mixes person + org while `pyproject.toml:13` lists only AgentMindCloud — **Severity:** Nit

**Long tail (not enumerated, ~15 more findings):** stale README links to preview-only sibling repos under `README.md:530-552`; Discord "coming soon" with no ETA at `README.md:586` and `docs/index.html:850`; bridge.live `app.py:99` `/static` mount has no length cap; passport.html dynamic config name not surfaced; `safety.py:21` docstring duplicates exit codes; multiple "v0.1 policy / future revisions" implicit-debt comments scattered; CHANGELOG tone mismatch in preface; bridge.live README jargon; templates with hardcoded latency/cost claims; mostly cosmetic.

---

## 3. Cross-Cutting Issues

- **Unescaped `@grok` mentions:** 1 live instance — `launch/x-thread.md:98` (also carries unescaped `@xai` and `@elonmusk`). Fix: wrap each handle in backticks (`` `@grok` ``) or rephrase ("Thanks to the xAI team and the Grok 4.20 model"). Other `@grok`-adjacent strings in the repo are inside `href` attributes pointing at x.com (auto-link safe) or inside JS template literals not GitHub-rendered.

- **Schema/version drift:** Three live drift sites, all on the `deploy.target` enum. Main schema (`grok_build_bridge/schema/bridge.schema.json:72`) lists 6 targets; `vscode/schemas/bridge.schema.json:128`, `vscode/snippets/bridge.code-snippets:17`, and `docs/index.html:714` all still list 4. The vscode schema also uses Draft-07 vs the main schema's Draft 2020-12. `marketplace/manifest.schema.json` is internally consistent at `schema_version: "1.0"` and pyproject `__version__` matches at `0.1.0`.

- **Documentation freshness:** Severe and consistent — the project has shipped faster than its docs. CHANGELOG only has `[0.1.0]`; ROADMAP says `publish --upload` is Week 7 future work but it shipped weeks ago; README contradicts itself within the same file (`--upload` shown in CLI table and called out as v0.3.0 future work); `marketplace/README.md` says "not yet wired" for `--upload`; pyproject description omits Railway/Fly.io; launch emails advertise five templates instead of eight; "Documentation site coming soon" while `docs/index.html` exists. The release workflow extracts release notes from CHANGELOG — every release after 0.1.0 will ship empty body.

- **Brand/visual consistency:** Genuinely strong. Neon-cyberpunk palette (`#00E5FF`, `#7C3AED`, `#FF4FD8`, `#0A0D14`) is consistent across `docs/index.html`, `bridge_live/static/style.css`, and the README hero. Inter/Space Grotesk/JetBrains Mono fonts. Focus rings, `aria-label`/`aria-expanded`, `prefers-reduced-motion`, `<noscript>` fallbacks. The single brand integrity problem is fabricated telemetry on the landing page (Critical above).

- **Dead code / orphan files:** `runtime.py:297` async `bridge` wrapper has no callers; `__init__.py:30-51` `__all__` lists submodules that aren't bound; `assets/buildbridge.gif` is broken; `docs/index.html` is unlinked from README; entire `launch/` directory presumes a v0.1.0 tag that never happened; `requirements.txt` exists alongside `pyproject.toml` with overlapping (and drift-prone) deps; `Dockerfile` exposes phantom port 8000.

- **Test coverage:** Genuinely strong. 163 test functions across 11 files; `--cov-fail-under=85` enforced in CI; matrix runs Python 3.10/3.11/3.12 × {ubuntu, macos}; `test_integration.py` parametrizes over every entry in `INDEX.yaml` so all 8 templates dry-run on every commit. Gaps: no Windows runner (path bugs latent — see `inspector.py` /tmp), no fuzz on YAML parser, no end-to-end test of the GitHub Action, no perf/load tests on bridge.live.

- **Security posture:** Clean on basics — no hardcoded secrets, `.env.example` minimal, `.gitignore` and `.dockerignore` correctly exclude `.env*`, all subprocess calls list-form with `check=True`. Trusted Publishing for PyPI (no long-lived tokens). However: the in-CI `pip-audit` is fully neutered by `|| true` + a placeholder GHSA ID; no GitHub Action is SHA-pinned (including the high-trust PyPI publish step); `bridge_live/Dockerfile` runs as root contrary to main image's non-root posture; `bridge_live/inspector.py` /tmp race + Linux-only path; no pre-commit hooks; no `SECURITY.md` for a project whose value prop is safety.

---

## 4. What's Working Well

- **Engineering discipline is unusually high for v0.1.0:** strict `mypy`, `ruff` lint+format gate, 85% coverage floor, 163 tests, schema-validation job that re-validates every bundled template on every commit. This is meaningfully more rigorous than typical pre-release Python projects.
- **Modular package architecture:** clean separation of `cli` / `runtime` / `parser` / `builder` / `deploy` / `safety` / `publish` / `xai_client` with consistent error handling via custom exception classes; `__init__.py:25-50` exports a stable SDK surface (`run_bridge`, result/exception types) that lets people use the package programmatically without going through Typer.
- **Visual identity is production-grade:** `docs/index.html` (1,189 lines) and `bridge_live/static/style.css` (341 lines) share the same neon palette, fonts, and accessibility patterns; this is rare in single-developer projects and gives the entire ecosystem a coherent look.
- **Safety architecture is well-designed:** regex `_patterns.py` + LLM dual scan with deterministic fallback in `safety.py`; `lucas_veto_enabled` flag is the structural hook for a two-gate Orchestra+Bridge composition; the safety gate writes structured reports the GitHub Action can post into PRs.
- **Composite GitHub Action + bridge.live + 8 templates** form a clear adoption funnel: a developer can copy `bridge-pr.example.yml` into their repo, paste a YAML into `bridge.live` to inspect it, and pick from 8 working templates — all within minutes. The funnel exists; what's missing is the PyPI release that activates it.

---

## 5. Top 5 Improvements (Ranked by Impact ÷ Effort)

| # | Improvement | Impact (1-10) | Effort (hours) | Why it matters |
|---|---|---|---|---|
| 1 | Tag `v0.1.0`, publish to PyPI via the wired Trusted-Publishing pipeline | 10 | 2 | Every README install instruction, the GitHub Action, the orchestra example, and three quick-start blocks point at `pip install grok-build-bridge`; today this 404s. Single highest-leverage move in the repo. |
| 2 | Fix wheel packaging to include `marketplace/manifest.schema.json` (add to `[tool.hatch.build.targets.wheel]` force-include) | 9 | 1 | `publish.py:106-114` will silently break for every PyPI installer the moment a release ships; this bug is invisible in editable dev mode. |
| 3 | Replace `assets/buildbridge.gif` with a real ≤30s screencap; fix `CHANGELOG.md:6` markdown syntax; relink from `launch/x-thread.md:7` | 8 | 4 | Launch playbook is gated on the demo asset; without it the X thread cannot post and the CHANGELOG renders broken. |
| 4 | Replace the fabricated landing-page telemetry on `docs/index.html:259-419, 1051-1139` with either real numbers or visually-explicit "demo mode" framing | 7 | 1 | For a safety-positioned product, fake live metrics with a 12px disclaimer is the highest credibility risk in the marketing surface. |
| 5 | Sync vscode schema + snippets to 6-target enum and add `pip-audit` real failure mode (remove `\|\| true`, drop placeholder GHSA) | 7 | 1.5 | Removes false-positive squiggles for VS Code users on valid configs; restores actual CI security gating that the workflow already pretends to provide. |

---

## 6. Quick Wins (≤30 min each)

- **Wrap handles in backticks** at `launch/x-thread.md:98`:
  - Replace `Thanks to @xai @grok @elonmusk` → `` Thanks to `@xai` `@grok` `@elonmusk` `` (or rephrase to remove handles entirely since this is X-handle prose, not a GitHub @-mention).
- **Sync vscode schema enum** at `vscode/schemas/bridge.schema.json:128` and snippet at `vscode/snippets/bridge.code-snippets:17`:
  - Change `"enum": ["x", "vercel", "render", "local"]` → `"enum": ["x", "vercel", "render", "railway", "flyio", "local"]`.
  - Apply the same edit to the snippet choice list `${5|local,x,vercel,render|}` → `${5|local,x,vercel,render,railway,flyio|}`.
- **De-neuter the safety gate** at `.github/workflows/ci.yml:169`:
  - Replace `pip-audit --strict --ignore-vuln GHSA-0000-0000-0000 || true` with `pip-audit --strict` (drop the placeholder ignore + the swallowed exit code).
- **Fix CHANGELOG image syntax** at `CHANGELOG.md:6`:
  - Either delete the line until the GIF exists or rewrite as `![Build Bridge demo](assets/buildbridge.gif)`.
- **Backfill CHANGELOG** with all post-0.1.0 waves (Wave 0 doctor, bridge-live, dev hot-reload, marketplace publish + `--upload`, link/fork, GitHub Action, Railway/Fly.io). Otherwise `release.yml:105-126` will publish empty release bodies for every future tag.
- **Remove "not yet wired" stub** at `marketplace/README.md:71-75` — `--upload` ships in `cli.py:982-990` and `publish.py:438-481`.
- **Update ROADMAP.md:117-122** — mark `publish --upload` as ✅ shipped instead of Week 7 future.
- **Strike the v0.3.0 contradiction** at `README.md:424` — `--upload` is shipped today.
- **Update pyproject description** at `pyproject.toml:8` to include Railway and Fly.io.
- **Update launch emails** — `launch/email-sales-xai.md:15` and `launch/email-media-xai.md:15-17`: change "five certified templates" → "eight"; reconcile "5 seconds" vs README's "~40 seconds".
- **Add SECURITY.md** with vuln-disclosure email and supported versions — table-stakes for a safety-positioned product and currently absent.
- **Reconcile pytest-asyncio** — either add to `pyproject.toml:[project.optional-dependencies].dev` or remove from `CONTRIBUTING.md:18`.
- **Drop or hide "Coverage 85%" badge** at `README.md:37` — it's the floor, not the actual; replace with a real Codecov badge or remove.
- **Drop or define "Lucas Certified" badge** at `README.md:19` — currently pure fabrication.
- **Link `docs/index.html`** from `README.md:585` instead of "Documentation site coming soon".
- **Remove `Final` annotation** from `grok_build_bridge/deploy.py:144-147` (`_GROK_INSTALL_AVAILABLE`) since tests `monkeypatch` it; or refactor tests to use a settable factory.
- **Remove `__all__` submodule names** from `grok_build_bridge/__init__.py:30-51` (or actually `import` them at top level) so `from grok_build_bridge import *` doesn't error.

---

## 7. Ecosystem Potential Statement

This is the load-bearing repo of the AgentMindCloud xAI/Grok stack: it owns the "deploy automation" gap between Grok-as-codegen and X-as-runtime, with a uniquely complete pipeline (YAML spec → xai-sdk codegen → regex+LLM safety scan → six-target deploy → marketplace publish) plus a forward-compatible manifest schema and a self-host inspector (`bridge.live`) that anticipate a registry that doesn't exist yet. Maturity is a striking split — **engineering is beta** (12 modules, 163 tests, 85% coverage gate, mypy strict, schema-check on every template, Trusted-Publishing wired, `Development Status :: 4 - Beta` declared in `pyproject.toml:16`) but **distribution is alpha** (no git tags, no PyPI release, broken demo GIF, launch playbook never executed despite being authored). On a 6-month horizon with a single-week push to ship v0.1.0 to PyPI plus a real screencap, realistic stars range is **300–1,500**, plausibly 2,500–5,000 with a single `@xai` retweet; revenue path runs through the marketplace if `grokagents.dev` materialises (listing fees, featured placement, signing); strategic value to AgentMindCloud is the highest in this audit because Bridge is the credible flagship that legitimises every preview-state sibling, and to the `@JanSol0s` X profile it's the asset most likely to anchor "this person can ship" perception. The single biggest unlock is **shipping v0.1.0 to PyPI within a week and replacing the fake landing-page telemetry with verifiable real numbers** — that converts the README from marketing fiction into a working `pip install` in one move, after which the GitHub Action, eight templates, and bridge.live all become demonstrable in under two minutes by anyone. Resource allocation: double down — this is the only repo in the sweep so far with production-grade engineering, and the gap between "what it can do" and "what people can use" is one release ceremony wide.

`POTENTIAL_TAG: DOUBLE_DOWN — Strong code/test/CI base; shipping PyPI release plus real demo unlocks immediate ecosystem credibility and adoption.`
