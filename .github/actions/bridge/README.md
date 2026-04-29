# Bridge Validate — GitHub Action

> Validate a `bridge.yaml`, dry-run the full pipeline, and post the
> result as a markdown comment on every pull request.

A composite action that wraps `grok-build-bridge validate` plus
`grok-build-bridge run --dry-run --allow-stub`. No XAI key required —
phase 2 falls back to the static-only path when `XAI_API_KEY` is not
set, so CI runs are free.

## Usage

```yaml
# .github/workflows/bridge-pr.yml
name: Bridge

on:
  pull_request:
    paths:
      - 'bridge.yaml'
      - '**/bridge.yaml'

permissions:
  contents: read
  pull-requests: write   # required for the PR comment

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: AgentMindCloud/grok-build-bridge/.github/actions/bridge@main
        with:
          config: bridge.yaml
```

That's it. On every PR that touches a `bridge.yaml`, the action will:

1. Install Python 3.12 + the latest `grok-build-bridge` wheel from PyPI.
2. Run `validate` (parse + schema + defaults).
3. Run `run --dry-run --allow-stub` (parse → generate → static safety).
4. Post a markdown summary as a PR comment, replacing the previous one.
5. Append the same summary to the GitHub Actions UI under "Job summary".
6. Fail the job if the safety scan blocked the deploy (exit 4) or any
   other phase exited non-zero.

## Inputs

| Name | Default | Purpose |
| --- | --- | --- |
| `config` | `bridge.yaml` | Path to the YAML file to inspect. |
| `python-version` | `3.12` | Python interpreter for `pip install`. |
| `package-version` | `grok-build-bridge` | `pip install` spec — pin a tag with `grok-build-bridge==0.1.0`, or test main with `git+https://github.com/AgentMindCloud/grok-build-bridge@main`. |
| `comment-on-pr` | `true` | Whether to post / update the PR comment. |
| `github-token` | `${{ github.token }}` | Token used for the PR comment. |
| `fail-on-safety` | `true` | Fail the job (non-zero) when the safety scan blocks the deploy. |

## Outputs

| Name | Meaning |
| --- | --- |
| `summary-file` | Path to the markdown summary file written by the action. |
| `validate-exit-code` | Exit code of `validate`. `0` = clean. |
| `dry-run-exit-code` | Exit code of `run --dry-run`. `0` = clean, `2` = config, `3` = runtime, `4` = safety block. |

## Why this exists

This is the retention half of the growth plan. Once a user has a
`bridge.yaml` in a repo, every PR that touches it surfaces:

- Schema regressions (a renamed field, a typo, a target you removed).
- Cost ceiling changes (`safety.max_tokens_per_run` doubled? PR comment shows it.).
- Safety findings the static catalogue can spot (new `os.system`, a
  hardcoded key, a `requests.get` without `timeout=`).
- Target switches (`x` → `vercel`?).

That feedback loop is what turns "I tried Bridge once" into "Bridge is
my deploy gate." See [the strategic plan](https://github.com/AgentMindCloud/grok-build-bridge#-roadmap)
for the full sequencing.
