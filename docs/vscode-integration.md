# VS Code integration

Grok Build Bridge ships a JSON Schema and five YAML snippets so writing
`grok-build-bridge.yaml` feels like writing TypeScript in VS Code:
autocomplete, enum choices, inline docs on hover.

## 1. Install the prerequisites

- [Visual Studio Code](https://code.visualstudio.com/) 1.80 or later.
- The **Red Hat YAML** extension
  ([`redhat.vscode-yaml`](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)) —
  this is what the Grok ecosystem extension composes on top of.
- The **Grok ecosystem VS Code extension** (from
  [`grok-install-ecosystem`](https://github.com/AgentMindCloud/grok-install-ecosystem)),
  patched with the entries from [`vscode/package.json.patch`](../vscode/package.json.patch).

## 2. Wire up the schema

If you are packaging the extension yourself:

1. Copy `vscode/schemas/bridge.schema.json` to `<extension>/schemas/bridge.schema.json`.
2. Copy `vscode/snippets/bridge.code-snippets` to `<extension>/snippets/bridge.code-snippets`.
3. Merge the entries in `vscode/package.json.patch` into the extension's
   `contributes.yamlValidation` and `contributes.snippets` arrays.
4. Rebuild the `.vsix` and install it.

If you are **not** building the extension and just want schema-powered
validation today, drop this into your user `settings.json`:

```json
"yaml.schemas": {
  "./vscode/schemas/bridge.schema.json": [
    "grok-build-bridge.yaml",
    "*.bridge.yaml"
  ]
}
```

Reload the window once and you are done.

## 3. Create a bridge YAML

Open VS Code in the repo, create a file named `grok-build-bridge.yaml`
(or anything matching `*.bridge.yaml`), type `bridge-min`, and press <kbd>Tab</kbd>:

![bridge-min snippet expanding into a minimal bridge YAML](./assets/vscode-bridge-min.png)

The snippet fills in a minimal valid document, parks your cursor on the
`name:` placeholder, and offers a multiple-choice dropdown on the
`language:` and `model:` fields.

## 4. IntelliSense you should see

Once the schema is loaded:

- Typing `version:` offers `1.0` as the sole completion.
- Typing `agent.model:` offers **grok-4.20-0309** or
  **grok-4.20-multi-agent-0309** with a side-by-side comparison of when
  to use each.
- Hovering over any key shows a short description with links back to
  [`docs/build-bridge.md`](./build-bridge.md).
- Invalid values (e.g. `name: Bad Name!`) get a squiggle immediately;
  `grok-build-bridge validate` confirms the same error.

## 5. All five snippets

| Prefix | What it inserts |
| --- | --- |
| `bridge-min` | Smallest valid bridge YAML — ready for `--dry-run`. |
| `bridge-x-trend` | X trend-analyzer skeleton with `required_tools: [x_search, web_search]` and a daily schedule. |
| `bridge-grok-source` | `build:` block that streams code from Grok. |
| `bridge-local-source` | `build:` block that uses a pre-existing entrypoint. |
| `bridge-safety` | Full `safety:` block with every flag set explicitly. |

## 6. Troubleshooting

- **Nothing auto-completes.** Check that the Red Hat YAML extension is
  installed and enabled. `yaml.schemas` only takes effect when the YAML
  language server is running.
- **Hovers are plain text, no markdown.** The Red Hat YAML extension
  renders `markdownDescription` / `markdownEnumDescriptions` only on
  recent versions — update to the latest release.
- **The schema is outdated.** The bundled schema is pinned to the same
  shape as `grok_build_bridge/schema/bridge.schema.json` in this repo.
  If `grok-build-bridge run` passes but VS Code flags your YAML, pull
  the latest `vscode/schemas/bridge.schema.json`.
