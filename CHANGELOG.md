## Fresh from the oven, v1.0 brand new version of the Build Bridge!!

Lots of exiting updates before the official launch, scroll down and you can see how many features Build Bridge has built in store for you all to enjoy! Please share your use cases, would be lovely to see how the X community uses this tool. <3

###
[assets/buildbridge.gif]

# Changelog

All notable changes to **grok-build-bridge** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-07

First public PyPI release.

### Added
- `grok-build-bridge` CLI (Typer-based) and Python SDK surface (`run_bridge`, `XAIClient`, `SafetyReport`, `load_yaml`).
- Two-layer safety audit: static checks plus LLM review (`grok_build_bridge.safety`).
- xai-sdk integration with retry/backoff (`grok_build_bridge.xai_client`).
- Multi-target deploy adapters (X / Vercel / Render / local) and dry-run mode (`grok_build_bridge.deploy`).
- YAML pipeline parser with JSON schema validation (`grok_build_bridge.parser`, `grok_build_bridge/schema/bridge.schema.json`).
- Bridge runtime, builder, and publish flows.
- Optional `bridge_live` Inspector + Showcase service (FastAPI / Uvicorn) under the `live` extra.
- VS Code IntelliSense assets and example bridges.
- Apache-2.0 license, OIDC PyPI Trusted Publishing workflow, and CI with ruff / pytest / coverage gates.

[Unreleased]: https://github.com/AgentMindCloud/grok-build-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AgentMindCloud/grok-build-bridge/releases/tag/v0.1.0
