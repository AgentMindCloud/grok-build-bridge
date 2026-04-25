# syntax=docker/dockerfile:1.6
#
# grok-build-bridge — multi-stage image
#
# Stage 1 (builder): installs build tools, creates a relocatable virtualenv,
#                    and performs the editable install with dev extras.
# Stage 2 (runtime): slim image that copies the venv + project source.
#                    No compilers, no pip cache, just the CLI ready to run.
#
# Build:   docker build -t grok-build-bridge:dev .
# Run:     docker run --rm --env-file .env grok-build-bridge:dev run examples/hello.yaml

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build-only OS deps. `git` is needed for any VCS-based wheels;
# `build-essential` covers source-only wheels (rare with our pinset).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

# Relocatable venv — copied wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy metadata + package source. Layer-cache friendly: changing tests/
# or docs/ does not bust the dep-install cache below.
COPY pyproject.toml README.md LICENSE ./
COPY grok_build_bridge ./grok_build_bridge

# Editable install pins the .pth path to /app/grok_build_bridge, which
# also exists in the runtime stage (see Stage 2 `COPY . .`).
RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# tini = real PID 1; forwards SIGINT/SIGTERM to the CLI cleanly so
# `docker stop` doesn't sit waiting on the 10-second kill timeout.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Bring the venv (with editable install + dev tools) over from the builder.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Full project — keeps tests/, examples/, docs/, templates/ available
# inside the container for `grok-build-bridge run examples/hello.yaml` etc.
COPY . .

# Reserved for the upcoming Typer-based status UI (roadmap Phase 4).
# Exposed now so docker-compose port mapping is stable when the UI lands.
EXPOSE 8000

# Cheap, reliable healthcheck: `version` proves the package imports and
# xai-sdk is wired up correctly. ~150ms locally.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD grok-build-bridge version >/dev/null 2>&1 || exit 1

# Entrypoint = the CLI itself, so `docker run <image> run foo.yaml` Just Works.
# Default CMD shows the banner + help; override with any subcommand.
ENTRYPOINT ["/usr/bin/tini", "--", "grok-build-bridge"]
CMD ["--help"]
