# API tasks. Run from this directory: `make seed`.
#
# make runs recipes under /bin/sh, which does not read your shell profile, so
# uv's default install location has to be put back on PATH explicitly.
export PATH := $(HOME)/.local/bin:$(PATH)

.DEFAULT_GOAL := help
.PHONY: help dev seed seed-live fixture migrate check

# Local Postgres, stated explicitly. api/.env may hold production
# credentials for deploys, and a dev server that quietly talks to production
# is both slow and dangerous.
LOCAL_DB ?= postgresql+asyncpg://postgres:postgres@localhost:5432/pokemon

help:
	@echo "dev        Run the API against local Postgres with auto-reload"
	@echo "seed       Seed Postgres from the committed fixture (default, offline)"
	@echo "seed-live  Seed Postgres from pokeapi.co (thousands of requests)"
	@echo "fixture    Regenerate fixtures/pokeapi-snapshot.json from pokeapi.co"
	@echo "migrate    Apply Alembic migrations"
	@echo "check      Lint, typecheck, and test"

# Auto-reload on save, pinned to local Postgres regardless of what .env says.
dev:
	DATABASE_URL="$(LOCAL_DB)" uv run uvicorn api.main:app --reload --port 8000

# Fixture is the default so that a stray `make seed` can never hammer PokeAPI.
seed:
	POKEAPI_SOURCE=fixture uv run python -m api.ingest.seed

seed-live:
	POKEAPI_SOURCE=live uv run python -m api.ingest.seed

fixture:
	uv run python -m api.ingest.fixture

migrate:
	uv run alembic upgrade head

check:
	uv run ruff check . && uv run ruff format --check . && uv run mypy api tests && uv run pytest -q
