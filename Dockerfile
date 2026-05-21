# syntax=docker/dockerfile:1.7

# Multi-stage build for codesearch-mcp.
# Builder: install Python deps with uv into a self-contained /app/.venv.
# Runtime: drop uv, install only git + ripgrep, copy /app over, run as non-root.

ARG PYTHON_VERSION=3.13

# --- builder stage -----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

# uv binary (pinned). Use the multi-arch image as a "scratch source".
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Lockfile + manifest first to keep the dependency layer cacheable.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Project source — install editable wheel into the same env.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime stage -----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# git and ripgrep are mandatory runtime dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID 10001 avoids collisions with common host UIDs.
ARG APP_UID=10001
RUN useradd --create-home --uid ${APP_UID} --shell /usr/sbin/nologin codesearch \
    && install -d -o codesearch -g codesearch /var/lib/codesearch/workspaces \
    && install -d -o codesearch -g codesearch /etc/codesearch

WORKDIR /app
COPY --from=builder --chown=codesearch:codesearch /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODE_SEARCH_WORKSPACE_ROOT=/var/lib/codesearch/workspaces

USER codesearch

VOLUME ["/var/lib/codesearch/workspaces"]
EXPOSE 8000

# tini reaps zombies for long-running git/rg subprocesses.
ENTRYPOINT ["/usr/bin/tini", "--", "codesearch-mcp"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
