# syntax=docker/dockerfile:1.6
#
# grok-build-bridge — multi-stage, non-root, cache-optimised image
#
# Stage 1 (builder): build tools + relocatable venv with editable install + dev extras.
# Stage 2 (runtime): slim image, non-root user, venv + source, healthcheck.
#
# Safety posture (mirrors README + dashboard):
#   * Runs as non-root (uid 10001) — no privilege escalation paths inside.
#   * The CLI's two-layer audit (static regex + Grok LLM) gates every deploy
#     and fails closed; this image does not bypass or weaken that contract.
#   * .dockerignore strips .env / secrets / caches; nothing sensitive is baked in.
#   * tini is PID 1 so `docker stop` cleanly cancels in-flight runs without
#     leaving the safety scan in an unknown state.
#
# Build:   DOCKER_BUILDKIT=1 docker build -t grok-build-bridge:latest .
# Run:     docker run --rm --env-file .env grok-build-bridge:latest run examples/hello.yaml

# =============================================================================
# Stage 1: builder
# =============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build-only OS deps. `git` covers VCS-based wheels; `build-essential`
# covers any source-only wheels (rare with the current pinset).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

# Relocatable venv — copied wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# ---- Layer 1: dependency-only install (cached unless pyproject.toml changes) --
# Copy ONLY the metadata + a stub package skeleton so hatchling can resolve
# the project name/version. Heavy dep resolution lives in this layer alone;
# editing source files below does NOT bust this cache.
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p grok_build_bridge \
    && printf '__version__ = "0.0.0"\n' > grok_build_bridge/__init__.py

# BuildKit cache mount keeps wheels across builds — full re-resolves stay fast.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install ".[dev]"

# ---- Layer 2: real source + editable re-link (fast; --no-deps) ----------------
COPY grok_build_bridge ./grok_build_bridge
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e . --no-deps

# =============================================================================
# Stage 2: runtime
# =============================================================================
FROM python:3.11-slim AS runtime

# OCI labels — surfaced by `docker inspect` and registries. The safety
# posture below is the same one advertised in the README and dashboard:
# every `grok-build-bridge run` inside this image runs the two-layer
# audit (static regex + Grok LLM) and fails closed before deploy.
LABEL org.opencontainers.image.title="grok-build-bridge" \
      org.opencontainers.image.description="Production-ready X agents from one YAML. Two-layer safety audit, fail-closed by default." \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/AgentMindCloud/grok-build-bridge" \
      org.opencontainers.image.documentation="https://github.com/AgentMindCloud/grok-build-bridge/blob/main/README.md" \
      io.grokagents.safety.audit="two-layer (static + grok-llm)" \
      io.grokagents.safety.fail-mode="closed" \
      io.grokagents.safety.runs-as="non-root (uid 10001)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# tini = real PID 1; forwards SIGINT/SIGTERM to the CLI cleanly so
# `docker stop` doesn't wait the full kill timeout.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
    && rm -rf /var/lib/apt/lists/*

# ---- Non-root user (UID/GID 10001) ------------------------------------------
# Static high UID dodges collisions with host users when bind-mounting in dev.
# Override at build time:  docker build --build-arg APP_UID=$(id -u) ...
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --system --gid ${APP_GID} app \
    && useradd --system --uid ${APP_UID} --gid app \
        --home /app --shell /bin/bash app

# Copy the venv with correct ownership so the non-root user can import / write.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

WORKDIR /app

# Full project — keeps tests/, examples/, docs/, templates/ available inside
# the container. .dockerignore strips secrets, caches, .git, etc.
COPY --chown=app:app . .

USER app

# Reserved for the upcoming Typer-based status UI (roadmap Phase 4).
# Exposed now so compose port mapping is stable when the UI lands.
EXPOSE 8000

# Cheap, reliable healthcheck: `version` proves the package imports and
# xai-sdk is wired up correctly. ~150 ms locally.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD grok-build-bridge version >/dev/null 2>&1 || exit 1

# Entrypoint = the CLI itself, so `docker run <image> run foo.yaml` Just Works.
# Default CMD shows the banner + help; override with any subcommand.
ENTRYPOINT ["/usr/bin/tini", "--", "grok-build-bridge"]
CMD ["--help"]
