# Grok Build Bridge — 30-day Roadmap

**Principle.** Every week ends with something a stranger can `pip install`,
read in one minute, and ship with in five. If a milestone can't survive that
test, it slides to the next week.

The first two weeks are about making Bridge so reliable nobody thinks about
it. The second two are about Orchestra — the multi-agent sibling that turns
Bridge's `lucas_veto_enabled` flag from a placeholder into a real governance
layer.

---

## Week 1 — Bridge polish

Aim: the "60-second Quick Start" in the README is actually 60 seconds for
first-time users, on every supported OS.

- [ ] **D1–2 — GIF demo.** Record the `run → dry-run → templates → init`
  loop at a readable pace. Land it at `docs/assets/bridge-demo.gif` and
  delete the placeholder.
- [ ] **D2 — PyPI trusted publishing live.** Tag `v0.1.0`, verify the
  release workflow publishes cleanly, confirm `pip install
  grok-build-bridge` returns the freshly-built wheel.
- [ ] **D3 — Windows CI.** Add `windows-latest` to the test matrix, fix
  the two or three path separators that will fall out.
- [ ] **D4 — `grok-build-bridge doctor`.** One subcommand that prints the
  Python version, SDK version, detected tools on `$PATH`, and whether
  `XAI_API_KEY` / `X_BEARER_TOKEN` resolve.
- [ ] **D5 — Bug triage pass.** File all issues that came in during soft
  launch, label `good-first-issue` on every one that takes <30 lines.

## Week 2 — Observability + batch

Aim: the people running two bridges now run ten.

- [ ] **Per-agent dashboards.** `grok-build-bridge status <name>` renders a
  Rich table of the last N runs: posts/day, audit-blocks, token burn,
  duration p50/p95.
- [ ] **Prometheus on request.** Optional `--metrics-port` flag that
  exposes the same numbers on `/metrics` for scraping.
- [ ] **Batch mode.** `grok-build-bridge run *.bridge.yaml` runs every
  config in parallel with a shared progress display; one failure does not
  cancel the others.
- [ ] **Grok-install action.** Publish a maintained GitHub Action that
  wraps `deploy_to_x` so CI-driven deploys stop relying on the fallback
  stub. Deprecate the stub's on-by-default behaviour.

## Week 3 — Orchestra foundation

Aim: the multi-agent companion project lands with Bridge as its plumbing.

- [ ] **Orchestra repo goes public.** Apache-2.0, separate package
  (`grok-orchestra`), depends on `grok-build-bridge`.
- [ ] **Named Lucas.** The first external consumer of
  `safety.lucas_veto_enabled`. Lucas is one concrete agent with one job:
  hold a veto on anything about to hit X. Wired via Bridge's existing
  safety hook.
- [ ] **Agent registry.** Orchestra ships a registry of agent roles
  (Lucas-veto, Ada-editor, Turing-fact-checker, …), each a signed Bridge
  template. Signing keys published alongside the release.
- [ ] **First end-to-end demo.** Three agents coordinated on one research
  question, vetoed by Lucas if the output drifts. Recorded as a separate
  GIF and linked from the Orchestra README.

## Week 4 — Orchestra launch + Bridge v0.2

Aim: the story the community retells is "Bridge ships single agents;
Orchestra ships teams."

- [ ] **Orchestra v0.1.0 on PyPI.** Same trusted-publishing pipeline.
- [ ] **Bridge v0.2.0.** Carries the doctor subcommand, the batch runner,
  and the Orchestra-aware `lucas_veto_enabled` wiring. Tag, release, PyPI
  live within 48 hours of Orchestra's drop.
- [ ] **Combined launch thread.** Single coordinated X thread from the
  AgentMindCloud account: one-liner on Bridge, one-liner on Orchestra,
  GIF, links. Replies amplified, not DMs solicited.
- [ ] **Docs merge.** A short `docs/orchestra.md` lives in this repo
  explaining how a Bridge YAML opts into Orchestra — the entry point for
  users coming to Bridge first.
- [ ] **Post-launch retro.** Public write-up of what shipped, what
  slipped, and what the next 30 days look like.

---

## Tracking

Each checkbox above is a GitHub issue under
[`AgentMindCloud/grok-build-bridge`](https://github.com/AgentMindCloud/grok-build-bridge/issues)
with one of four labels — `week-1`, `week-2`, `week-3`, `week-4`. The
milestones mirror the four sections; PRs link to their issue; issues
close when the PR merges.

If a week's items don't all ship, the roadmap updates the next Monday
with the slip called out explicitly — no silent rescheduling.
