# syntax=docker/dockerfile:1.7
#
# KaraForge image.  Two variants are built from this one file:
#   docker build -f docker/Dockerfile --build-arg VARIANT=cpu  -t karaforge:cpu  .
#   docker build -f docker/Dockerfile --build-arg VARIANT=cuda -t karaforge:cuda .
# Model weights are never baked in: they live in the volume mounted at /data/home (see
# docker/docker-compose.yml), together with user themes and fonts.

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=24
ARG UV_VERSION=0.13.9

# ---------------------------------------------------------------- web: build the frontend
FROM node:${NODE_VERSION}-trixie-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- uv binary
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------- builder: Python environment
FROM python:${PYTHON_VERSION}-slim-trixie AS builder
ARG VARIANT=cpu
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so that source edits do not invalidate this layer.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra "${VARIANT}"
COPY engine/ engine/
COPY bench/ bench/
COPY fonts/ fonts/
COPY themes/ themes/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra "${VARIANT}"

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ARG VARIANT=cpu
LABEL org.opencontainers.image.title="KaraForge" \
      org.opencontainers.image.description="Open-source KTV karaoke video generator" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.karaforge.variant="${VARIANT}"

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

# The data folders are writable by any user id, so that the container can also be started
# with the id of whoever owns a bind-mounted projects folder (`docker run --user ...`).
RUN groupadd --gid 1000 karaforge \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin karaforge \
    && mkdir -p /data/home /data/projects \
    && chown -R karaforge:karaforge /data \
    && chmod 1777 /data/home /data/projects

COPY --from=builder /app/.venv /app/.venv
COPY --from=web /src/web/dist /app/web

# HOME and the caches of the numeric libraries point at places every user id can write to.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HOME=/data/home \
    XDG_CACHE_HOME=/data/home/.cache \
    NUMBA_CACHE_DIR=/tmp/numba-cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    KARAFORGE_HOME=/data/home \
    KARAFORGE_WORKSPACE=/data/projects \
    KARAFORGE_WEB_DIST=/app/web

USER karaforge
WORKDIR /data/projects
VOLUME ["/data/home", "/data/projects"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["tini", "--", "kf"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
