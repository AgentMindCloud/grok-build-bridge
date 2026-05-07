<!--
╔══════════════════════════════════════════════════════════════════════════════╗
║  MERGE_PLAN · grok-build-bridge                                              ║
║  Phase rollout & visual-identity ledger for the combined Bridge + Orchestra  ║
║  product surface inside AgentMindCloud.                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
-->

# MERGE_PLAN

This file tracks the consolidated rollout for **grok-build-bridge** — the merged
Bridge + Orchestra product surface — as it moves through phased polish tiers.
Each tier is a contract: scope, palette, type stack, and what "done" looks like.

| Tier | Theme | Owner repo | Status |
| :--: | :---- | :--------- | :----: |
| Tier 1 | Functional merge — Orchestra integration into Bridge pipeline (Phase 13) | `grok-build-bridge` | ✅ |
| Tier 2 | Documentation pass — combined CLI surface, docs site outline | `grok-build-bridge` | ✅ |
| Tier 3 | Audit + portfolio polish (`AUDIT-REPORT.md`, branch hygiene) | `grok-build-bridge` | ✅ |
| **Tier 4** | **Spectral visual identity — README hero, palette, typography (Phase 18)** | **`grok-build-bridge`** | **✅** |

---

## ✦ Tier 4 · Spectral Visual Identity (Phase 18)

**Branch:** `claude/spectral-visual-identity-U3Kua`
**Date:** 2026-05-07
**Scope:** Apply the ultra-premium **Spectral** visual system to the combined
grok-build-bridge product surface so the repo presents at the same tier as
`grok-install` after its Phase 17 polish.

### Palette

| Token | Hex | Role |
| :---- | :-- | :--- |
| **Plasma** | `#FF1E70` | Primary brand, energy, emphasis, alerts |
| **Aurora** | `#00E0D5` | Verdicts, clarity, runtime cues |
| **Nebula** | `#7C3AED` | Depth, reasoning, generation phase |
| Background | `#0A0A0A` | Canvas (replaces `#0A0D14` cyberpunk slate) |
| Surface    | `#12121A` | Elevated surface, terminal chrome |
| Text       | `#EAF8FF` | Cool-white body text |

### Type stack

- **Inter** — display, headings, body, capsule render text
- **JetBrains Mono** — terminal SVG, CLI receipts, code blocks

### Texture vocabulary

- **Nebula circles** — soft radial gradients (Plasma / Aurora / Nebula) under
  hero and result panels.
- **Halftone dot lattice** — `<pattern>`-based 6 px dot grid at 5 % opacity over
  deep surfaces, used in the inline terminal SVG.
- **Chromatic aberration** — referenced in the visual-language footer; the SVG
  primitives (Plasma-left, Aurora-right offsets) ship in the system but are
  applied sparingly.

### What changed in this tier

- **`README.md` hero region rebuilt:**
  - SPECTRAL header comment block replaces `NEON / CYBERPUNK` template marker.
  - Capsule render gradient migrated to `0:FF1E70 → 50:7C3AED → 100:00E0D5`.
  - Typing-SVG migrated from Space Grotesk → **Inter**, color → Aurora, with a
    new line advertising the built-in multi-agent runtime.
  - Inline terminal SVG fully redrawn: Spectral palette, JetBrains Mono / Inter
    fonts, nebula radial gradients, halftone overlay, gradient verdict panel.
  - Tagline upgraded to mention multi-agent runtime explicitly.
- **New H2 — `## ✦ Now with Built-in Multi-Agent Runtime (Orchestra)`**
  inserted as the first section after the hero divider. Spectral-tier badges,
  side-by-side YAML + CLI demonstrating the `lucas_veto_enabled` one-liner.
- **Body sweep:** all in-body shields.io badges, Mermaid `classDef`s, and
  inline color references migrated from cyberpunk hex to Spectral hex via
  exhaustive replace passes (`00E5FF`, `00D5FF`, `5EF2FF`, `FF4FD8`, `0A0D14`,
  `001018` → Spectral equivalents). 62 Spectral hex occurrences in the final
  README; zero legacy hex remain.
- **New H2 — `## ✦ Visual Language`** footer documents the Spectral system
  (palette swatches, type stack, texture vocabulary) so the system is
  discoverable to maintainers and downstream surfaces.
- **Closing capsule** gradient migrated to Plasma → Nebula → Aurora.

### Out of scope (intentionally not touched)

- The single binary asset `assets/buildbridge.gif` — kept untouched per
  Tier 4 brief (visual-language pass, not asset regeneration).
- `docs/index.html` (64 KB landing page) — separate landing-page pass.
- Cloudflare worker / any other repo — Tier 4 is single-repo polish.

### Verification gates

- [x] Pre-flight: correct repo, clean tree, git available.
- [x] Branch hygiene: no stale branches; only `main` and active feature branch.
- [x] Hero, badges, terminal SVG all on Spectral palette.
- [x] Inter / JetBrains Mono explicit in display + monospace contexts.
- [x] Orchestra section added with premium Spectral treatment.
- [x] Visual-language footer documents the system.
- [x] No legacy palette hex remains in `README.md`.

---

## ✦ Forward outlook (not part of Phase 18)

- **Tier 5** — landing page (`docs/index.html`) Spectral pass.
- **Tier 5** — OG image regeneration in Spectral palette (PNG/SVG export).
- **Tier 5** — VS Code extension theme aligned with Spectral.

These are tracked here for visibility but explicitly **out of scope** for the
current phase. No work has been started on them.
