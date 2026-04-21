# Seven-day shipping plan

Solo-dev, zero-budget, Vietnam timezone (ICT = UTC+7). The plan optimises
for one thing: within seven days, a stranger on X sees Bridge, runs it,
and tells somebody else. Everything else is a distraction.

Every day lists the minimum viable outcome in **bold** — if you hit that,
the day is a win even if the "stretch" tasks slip.

---

## Day 1 (Mon) — CI green on GitHub

**Minimum:** every badge in the README is green on `main`.

- 09:00 ICT — push latest branch to `main`; watch the five CI jobs
  (lint, test matrix, schema-check, safety-scan, build). Fix whatever
  breaks on macOS or Python 3.10.
- Land a `v0.1.0` tag **only** after every job is green. The
  `release.yml` workflow cuts the PyPI release automatically.
- Stretch: enable branch protection so nobody (including you) can merge
  a red PR.

**End-of-day proof:** `pip install grok-build-bridge==0.1.0` works from
any machine.

---

## Day 2 (Tue) — Record the demo GIF

**Minimum:** `docs/assets/bridge-demo.gif` exists and renders inline on
the GitHub README.

- Terminal: 120 columns × 32 rows, dark theme, 18pt mono font.
- Record `grok-build-bridge templates` → `init x-trend-analyzer` →
  `validate bridge.yaml` → `run bridge.yaml --dry-run` in one take.
  Use `asciinema` → `agg` to produce a 30-second sub-2MB GIF.
- Commit the GIF, push, verify the README preview on github.com.
- Stretch: record an alt GIF showing a failing safety scan + the
  red panel + `--force` recovery, for the CONTRIBUTING docs.

**End-of-day proof:** the README hero animates on mobile GitHub.

---

## Day 3 (Wed) — PyPI polish + docs link-check

**Minimum:** the PyPI page looks as good as the GitHub README.

- Render the README locally with `python -m readme_renderer` or a
  preview tool; fix any markdown that renders weirdly on PyPI (it does
  not support GitHub callouts or colored badges).
- Run the link-check workflow; fix any 404s (most commonly the GIF or
  template paths if they moved).
- Publish the VS Code extension package.json patch to the ecosystem
  extension's repo — `grok-install-ecosystem` maintainers accept PRs.
- Stretch: add the Bridge schema URL to
  [schemastore.org](https://schemastore.org) so `grok-build-bridge.yaml`
  auto-validates for every YAML editor globally.

**End-of-day proof:** opening the PyPI page shows the hero,
the quick-start, and at least one badge.

---

## Day 4 (Thu) — Soft launch: the X thread

**Minimum:** the eight-tweet launch thread is live.

- 10:00 ICT (20:00 PT previous evening in US) post the thread from
  `@AgentMindCloud` with the Day-2 GIF attached to tweet 1. Pick the
  hook variant you'll refer to in tomorrow's DMs.
- Pin the thread on the profile. Don't quote-tweet yourself during the
  run; that kills reach on X's current feed algorithm.
- Spend 2 hours replying to every interaction in the first 6 hours
  post-launch (the reply rate is what the algorithm weights highest).
- Stretch: start a follow-up reply with the first user's screenshot when
  it arrives (this becomes Day-7 content).

**End-of-day proof:** tweet 1 ≥ 500 impressions, ≥ 10 replies.

---

## Day 5 (Fri) — DM 10 Grok power-users

**Minimum:** ten well-targeted, personalised DMs sent; zero mass blasts.

- List: ten accounts who have posted concretely about Grok 4.20 in the
  last 14 days (not follower-farmers; look for actual technical tweets).
- Each DM: 2 lines max — name the thing they posted about, drop the
  launch-thread link, say "would love your 2-minute take on the YAML."
  No "following up?" follow-ups.
- Log each DM in `launch/dm-log.md` (gitignored) with date + handle +
  whether they engaged.
- Stretch: post one standalone tweet showcasing a power-user's
  screenshot with their consent.

**End-of-day proof:** ≥ 3 of the 10 engaged (reply, quote, follow).

---

## Day 6 (Sat) — Email xAI sales + media

**Minimum:** `launch/email-sales-xai.md` and `launch/email-media-xai.md`
sent verbatim.

- Send from the `jan@agentmind.cloud` address at 14:00 ICT
  (which lands in the SF team's morning the same day).
- No attachments — the emails already link to the repo and the thread.
- Stretch: cross-post the launch thread's content as a LinkedIn
  long-form article, linking back to X for the thread itself.

**End-of-day proof:** two emails sent with the exact subjects above;
thread impressions ≥ 5k (that's the social proof xAI checks if they read
the email).

---

## Day 7 (Sun) — Follow-up post + retro

**Minimum:** a screenshot-driven follow-up tweet is live, retro written.

- Thread it with tweet 1 of the launch: "Day 7 update —" plus 2-3
  screenshots from users who shipped a bridge in the first week. Credit
  each user by handle.
- Write a `launch/retro-week-1.md` (gitignored until Week 2) capturing:
  what worked, what didn't, ship-through vs. expectation, top 3 bug
  reports to address next week.
- Merge any `good-first-issue` PRs that came in during the week.
- Stretch: schedule Week 2's kick-off tweet ("observability lands next
  Friday — here's the design") for Monday 10:00 ICT.

**End-of-day proof:** the Day-7 tweet shows at least one external user
shipping a Bridge-built agent.

---

## Hard rules for all seven days

- **Don't touch Orchestra code this week.** It's week 3 territory.
  Shipping Bridge clean is more important than shipping Orchestra late.
- **Don't chase features.** If a request doesn't match the README, note
  it and keep going.
- **Don't argue on X.** Reply once to clarify, then stop. Your time is
  better spent merging a PR than proving a point.
- **Protect one hour of deep work per day.** 05:00–06:00 ICT is before
  the US wakes up and before Vietnam notifications start; use it for
  code, not marketing.
