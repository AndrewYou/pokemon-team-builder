# Convenience targets for the API. All of them run inside api/ via uv.
.DEFAULT_GOAL := help
.PHONY: help seed seed-live fixture migrate check

help:
	@echo "seed       Seed Postgres from the committed fixture (default, offline)"
	@echo "seed-live  Seed Postgres from pokeapi.co (thousands of requests)"
	@echo "fixture    Regenerate fixtures/pokeapi-snapshot.json from pokeapi.co"
	@echo "migrate    Apply Alembic migrations"
	@echo "check      Lint, typecheck, and test"

# Fixture is the default so that a stray `make seed` can never hammer PokeAPI.
seed:
	cd api && POKEAPI_SOURCE=fixture uv run python -m api.ingest.seed

seed-live:
	cd api && POKEAPI_SOURCE=live uv run python -m api.ingest.seed

fixture:
	cd api && uv run python -m api.ingest.fixture

migrate:
	cd api && uv run alembic upgrade head

check:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy api tests && uv run pytest -q
