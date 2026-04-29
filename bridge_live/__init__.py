"""``bridge.live`` — Inspector + Showcase web service.

A small FastAPI application that turns a ``bridge.yaml`` into a public,
shareable "agent passport" page. The service runs phases 1 (parse +
schema-validate) and 3 (static safety scan) of the Bridge pipeline —
no Grok calls, no XAI key required, no deploy. The output is a
read-only artefact: target, model, safety verdict, cost estimate,
file list, plus a copy-paste "run locally" snippet.

Deployment: see ``bridge_live/README.md``. Designed to run on any host
that takes a Python process or a container — Render, Fly.io, Railway,
Vercel (with a Python runtime), or self-hosted.

Three external surfaces:

* ``GET  /``                — paste-or-upload landing page.
* ``POST /p``               — render a passport from a posted YAML.
* ``GET  /p/<sha8>``        — view the passport at its public URL.
* ``GET  /showcase``        — gallery seeded with the 8 bundled templates.
* ``GET  /launch?topic=...`` — query-string handoff, pre-fills a YAML
  derived from the ``x-trend-analyzer`` template for the given topic.
"""

from __future__ import annotations

__all__ = ["create_app"]

from bridge_live.app import create_app
