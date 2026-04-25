# Orchestra → Bridge: Weekly Research Thread Publisher

End-to-end example showing the full **Grok Agent Orchestra → Grok Build Bridge**
handoff. Orchestra runs a multi-agent debate to produce a vetted research
brief; Bridge turns that brief into a safely-deployed weekly X thread.

```
┌─────────────────────────────────┐        ┌─────────────────────────────────┐
│  Orchestra                      │        │  Bridge                         │
│  ───────────────────────────    │        │  ───────────────────────────    │
│  researcher → critic → debate   │        │  generate Python from brief     │
│  → synthesizer → Lucas veto     │ ─────▶ │  → static + Grok safety audit   │
│  ──────────────────────         │ brief  │  → deploy to X (cron weekly)    │
│  out/research-brief.md          │        │  out/main.py + grok-install     │
│  out/veto-report.json (PASS)    │        │                                 │
└─────────────────────────────────┘        └─────────────────────────────────┘
       Lucas veto (epistemic gate)              Bridge audit (code gate)
```

Two safety layers, two artefacts, one deployable agent.

## Files in this folder

| File                  | Tool       | Purpose                                                                 |
| --------------------- | ---------- | ----------------------------------------------------------------------- |
| `orchestra-spec.yaml` | Orchestra  | Multi-agent debate + Lucas veto gate. Outputs `out/research-brief.md`.  |
| `bridge.yaml`         | Bridge     | Generates the X publisher from the brief. Honours the Lucas verdict.    |
| `README.md`           | (this)     | Workflow walkthrough + safety-gate explanation.                         |

## Prerequisites

```bash
pip install grok-build-bridge grok-agent-orchestra
cp ../../.env.example .env
# Fill in XAI_API_KEY and X_BEARER_TOKEN
```

> If you do not have `grok-agent-orchestra` installed yet, see the [Orchestra
> repo][orch]. The Bridge half of this example runs standalone as long as you
> hand-author `out/research-brief.md` and a passing `out/veto-report.json`.

[orch]: https://github.com/agentmindcloud/grok-agent-orchestra

## Step 1 — Run Orchestra (debate + research)

```bash
cd examples/orchestra-bridge
grok-orchestra run orchestra-spec.yaml \
    --set topic="Progress in RLHF" \
    --out ./out
```

Orchestra walks four phases:

1. **research** — `researcher` agent surfaces 8-12 candidate findings using
   `x_search` + `web_search`, attaches primary sources.
2. **debate** — `critic` agent challenges every finding for two rounds; the
   `researcher` rebuts. Surviving findings move forward.
3. **synthesize** — `synthesizer` merges into a publication-ready
   `research-brief.md` (TL;DR + 5-7 evidence sections).
4. **veto_gate** — `lucas_veto` reads the final brief and emits PASS or VETO.
   On VETO, Orchestra exits non-zero and `bridge.yaml` is **never** invoked.

Artefacts after a successful run:

```
out/
├── research-brief.md          ← human-readable brief, consumed by bridge.yaml
├── debate-transcript.json     ← full agent log, useful for audit trails
└── veto-report.json           ← {"verdict": "PASS"} on success
```

## Step 2 — Run Bridge (safe deployment)

Only proceed once `out/veto-report.json` shows `"verdict": "PASS"`.

```bash
# Dry-run first — generates main.py, runs the safety audit, but does NOT post:
grok-build-bridge run bridge.yaml --dry-run

# Promote to a real deploy when the dry-run looks clean:
grok-build-bridge run bridge.yaml
```

What Bridge does:

1. **build** — Calls Grok 4.20 with the prompt from `bridge.yaml`, embedding
   the Orchestra brief as the authoritative content source. Generates one
   `main.py`.
2. **safety_scan** — Two-layer audit on the generated code:
   - Static regex pass (blocks `eval`, `exec`, `shell=True`, `os.system`,
     `pickle`, secret leaks).
   - Grok LLM review (semantic check: would this misbehave at runtime?).
   Fails closed — any finding aborts deploy.
3. **lucas_veto check** — `safety.lucas_veto_enabled: true` makes Bridge read
   `out/veto-report.json`. Anything other than `PASS` aborts deploy.
4. **deploy** — Hands off to `grok-install`'s `deploy_to_x` runtime. Schedule
   `0 13 * * 1` posts the thread every Monday at 13:00 UTC.

## The two safety gates, working together

| Gate                    | Owner       | What it catches                                                                  | Failure mode |
| ----------------------- | ----------- | -------------------------------------------------------------------------------- | ------------ |
| **Lucas veto**          | Orchestra   | Epistemic / alignment / reputational risk in the *brief* (unsourced claims, bias, harmful recommendations, stale citations). | Hard abort. Bridge never runs. |
| **Bridge safety audit** | Bridge      | Code-level risk in the *generated agent* (unsafe APIs, secret leakage, missing retries, prompt-injection vectors).            | Hard abort. Deploy never ships. |

The two gates cover different failure modes and never substitute for each other:

- **Lucas alone** can clear a brief that the generated code mishandles
  (e.g. forgets to verify post length).
- **Bridge alone** can clear safe code that publishes an unsourced claim.

Running them together gives a defence-in-depth posture: a release ships only
when *both the source material and the executable* pass independent review.

## Re-running on a new topic

The brief is the only artefact tied to a specific topic. To rotate topics
weekly without rerunning Bridge:

```bash
# 1. Refresh the brief with a new Orchestra run (cheap; ~$0.80).
grok-orchestra run orchestra-spec.yaml --set topic="New topic here" --out ./out

# 2. Bridge already deployed — the agent reads ./out/research-brief.md at
#    runtime, so the next scheduled tick picks up the new content.
```

If the new run yields a VETO, the previously-deployed agent keeps running on
the previous brief — no risky degraded mode.

## Troubleshooting

| Symptom                                                  | Fix                                                                            |
| -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `bridge.yaml` aborts with `lucas_veto_enabled requires out/veto-report.json` | Run Orchestra first, or hand-author a `{"verdict": "PASS"}` file for a smoke test. |
| Static safety scan flags a generated regex                | Inspect the finding in the Bridge console; tighten `grok_prompt` constraints.  |
| `grok-orchestra: command not found`                       | `pip install grok-agent-orchestra` (or skip Orchestra and author the brief manually). |
| Schedule fired but no post appeared on X                  | Check `X_BEARER_TOKEN` scope — needs `tweet.write` and a Pro tier app.         |

## What this example does NOT cover

- Multi-account fan-out (one brief → multiple X handles). Use a separate
  `bridge.yaml` per handle and share the same `out/research-brief.md`.
- Real-time refresh. Both halves are batch — Orchestra ad-hoc, Bridge weekly.
  For real-time, see the `x-trend-analyzer` template instead.
- Custom Lucas criteria. Edit `veto_criteria` in `orchestra-spec.yaml`, or
  point `LUCAS_VETO_RULES` at a longer ruleset YAML before running Orchestra.
