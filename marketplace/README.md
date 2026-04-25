# marketplace/ — registry foundation

This folder holds the **public contract** between Grok Build Bridge and the
upcoming agent registry at [grokagents.dev](https://grokagents.dev). The
registry is not live yet; everything here is forward-compatible scaffolding
so packages produced today validate against the schema the registry will
ship with.

## Contents

| File                      | Purpose                                                                     |
| ------------------------- | --------------------------------------------------------------------------- |
| `manifest.schema.json`    | JSON Schema (Draft 2020-12) for the manifest emitted by `grok-build-bridge publish`. |
| `example.manifest.json`   | Reference manifest. Validates against the schema; mirrors the structure `publish` produces.   |
| `README.md`               | This file.                                                                  |

## How the pieces fit together

```
bridge.yaml                ← user-authored
   │
   ▼
grok-build-bridge run      ← phase 1–5 pipeline (parse, generate, audit, deploy)
   │
   ▼
generated/<slug>/main.py + bridge.manifest.json
   │
   ▼
grok-build-bridge publish  ← reads the above, emits a marketplace manifest
   │
   ▼
dist/marketplace/<slug>-<version>.zip
   │     ├── manifest.json   ← validated against marketplace/manifest.schema.json
   │     ├── bridge.yaml
   │     └── main.py         ← optional, only if --include-build
   ▼
grokagents.dev               ← future upload endpoint
```

## Validating a manifest locally

```bash
python -c "
import json, jsonschema, pathlib
schema   = json.loads(pathlib.Path('marketplace/manifest.schema.json').read_text())
manifest = json.loads(pathlib.Path('marketplace/example.manifest.json').read_text())
jsonschema.validate(manifest, schema)
print('manifest valid')
"
```

The `publish` command runs this validation automatically before writing the
zip — a manifest that fails the schema aborts with exit code `2`
(`BridgeConfigError`).

## Forward compatibility

The schema is **strict** (`additionalProperties: false`) and pins
`schema_version` to a single value (`"1.0"`). When the registry needs new
fields it bumps `schema_version` and consumers refuse manifests they do not
understand. This is the same versioning discipline used by `bridge.yaml`
itself (`grok_build_bridge/schema/bridge.schema.json`) — one schema bump,
one explicit consumer migration.

Optional fields (`safety`, `package`, `marketplace`, `categories`,
`keywords`, `homepage`, `repository`) can be omitted in v1.0 manifests
without breaking validation. The registry treats their absence as
"unknown" rather than rejecting the submission.

## Not yet wired

- **Upload endpoint** — `grok-build-bridge publish --upload` will exist
  once the registry API ships. For now the command stops after writing the
  zip and prints the future endpoint URL.
- **Signature** — packages will carry a Sigstore signature in v1.1. The
  schema will gain a `signature` block; v1.0 packages remain valid.
- **Reverse-resolution** — the registry will let you `grok-build-bridge install <slug>` once it ships, restoring the package to a working bridge layout.
