# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies resolve in their own layer so app edits do not bust the cache.
# No --mount=type=cache here on purpose: Railway requires cache mount ids to be
# prefixed with the service id, which would pin this image to one service. The
# layer cache already covers the common case, since this step is skipped
# entirely unless pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY api ./api

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrations run before the server so a deploy that adds a table cannot leave
# the API answering 500s against an older schema. The `&&` is deliberate: if the
# migration fails the container must not come up serving a half-migrated
# database. Alembic falls back to DATABASE_URL when ALEMBIC_DATABASE_URL is
# unset, so the platform only has to configure one variable.
#
# 0.0.0.0 is mandatory: binding 127.0.0.1 yields a container that starts fine
# and is unreachable from outside. Railway injects $PORT; the fallback keeps
# plain `docker run` and docker-compose working, where PORT is unset.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
