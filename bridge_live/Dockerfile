# bridge.live — Inspector + Showcase service.
#
# Single-stage, slim image. Targets `python -m uvicorn` rather than a
# WSGI runner because the FastAPI surface is tiny and the dev experience
# stays the same as ``uvicorn bridge_live.app:app --reload`` locally.
FROM python:3.12-slim

# ---- system layer -----------------------------------------------------------
# ``--no-install-recommends`` keeps the image close to 90 MB; without it,
# Debian pulls in ~30 MB of compiler/man-page extras we never use.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# ---- python layer -----------------------------------------------------------
WORKDIR /app

# Install the package first so Docker layers cache cleanly when only
# the YAML/templates change but the dep set is stable.
COPY pyproject.toml README.md LICENSE ./
COPY grok_build_bridge ./grok_build_bridge
COPY bridge_live ./bridge_live

# ``[live]`` extras pull fastapi/uvicorn/jinja2/python-multipart on top
# of the core CLI deps. ``--no-cache-dir`` shaves ~40 MB off the image.
RUN pip install --no-cache-dir ".[live]"

# Persist passports across restarts when the host mounts a volume.
ENV BRIDGE_LIVE_HOME=/data/passports
RUN mkdir -p ${BRIDGE_LIVE_HOME}
VOLUME ["/data/passports"]

# ---- runtime ----------------------------------------------------------------
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

# ``--proxy-headers`` lets uvicorn trust X-Forwarded-* from a TLS-terminating
# proxy (Render, Fly.io, Railway, Vercel all set these). One worker is plenty
# for the read-only inspector at the traffic levels v0.1 will see.
CMD ["sh", "-c", "uvicorn bridge_live.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
