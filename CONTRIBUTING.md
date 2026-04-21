# Contributing to Grok Build Bridge

Thanks for the help — Bridge gets better every time someone points at a
rough edge. This guide covers the short version of what a good PR looks
like.

## Dev setup

```bash
git clone https://github.com/AgentMindCloud/grok-build-bridge.git
cd grok-build-bridge
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

That installs the package editable, plus `pytest`, `pytest-cov`,
`pytest-asyncio`, `mypy`, `ruff`, `build`, and the `types-*` stubs mypy
strict needs.

## Run the same gates CI runs

```bash
ruff check .
ruff format --check .
mypy grok_build_bridge
pytest --cov=grok_build_bridge --cov-fail-under=85
python -m build          # only when touching packaging
```

If any of these fail locally, your PR will fail on GitHub Actions — there
is no skip-CI in the release workflow. Fix them before opening the PR.

## Branch naming

- `feat/<slug>` — new features.
- `fix/<slug>` — bug fixes.
- `docs/<slug>` — documentation only.
- `chore/<slug>` — tooling, CI, refactor with no behaviour change.
- `claude/<slug>` — reserved for agent-driven work.

## Commit messages

Conventional Commits, imperative mood, present tense.

```text
feat(safety): add unsafe-deserialization pattern for marshal.loads
fix(parser): lift missing key into key_path on required-failure
docs(readme): fix broken link to templates page
```

Keep the first line ≤ 72 chars. Use the body for the *why*, not the
*what* — the diff already shows the what.

## PR checklist

Before requesting review, tick every box:

- [ ] `ruff check .` passes locally.
- [ ] `ruff format --check .` passes locally.
- [ ] `mypy grok_build_bridge` is clean (strict mode; no `# type: ignore`
  added without a one-line justification comment).
- [ ] `pytest` is green and overall coverage stays **≥ 85 %**.
- [ ] Public API changes are reflected in both `grok_build_bridge/schema/bridge.schema.json`
  and `vscode/schemas/bridge.schema.json`.
- [ ] New user-facing behaviour has an entry in `CHANGELOG.md` under
  `[Unreleased]`.
- [ ] If you touched an error path, the error carries an actionable
  `suggestion=`.
- [ ] If you touched a file path resolver, you considered Windows.

## Filing an issue

Two things save triage time:

1. **The exact command you ran**, pasted verbatim.
2. **The full Rich panel the CLI printed.** The panel already carries the
   error type, the key path, and a suggestion — don't paraphrase.

Opinions welcome, vague complaints less so. If you have a design
disagreement, say "I would expect X because Y" and we will have a good
discussion.

## Releasing

Releases are cut by tagging `main` with `vX.Y.Z`:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The [`release.yml`](.github/workflows/release.yml) workflow then builds
the wheel + sdist, publishes to PyPI via trusted publishing, extracts the
matching section from `CHANGELOG.md`, and creates a GitHub Release with
the dist files attached. No secrets to rotate, no manual steps.
