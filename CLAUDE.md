# Pokémon Team Builder

Take-home case study. Monorepo:
  /api  — Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2
  /web  — React 19 + Vite + TypeScript, Tailwind, shadcn/ui
Database: Neon Postgres. API on Railway, frontend on Vercel.

## Core design decision
We snapshot PokéAPI into our own Postgres rather than proxying at request
time. This makes the grid fast AND is the prerequisite for change detection
(Task 2) — you cannot diff against an API you don't have a prior copy of.

## Rules
- Store BASE stats from PokéAPI. Convert to level-50 in the derived layer,
  never at write time, so diffs compare like with like.
- Level 50, no EVs/IVs, neutral nature, average damage roll. These are
  declared simplifications, not oversights.
- Derived data (type lookups, defensive vectors, best-move lists) is built
  once at app startup and held in memory. Never materialize it as tables.
- Static JSON files are build inputs only (seed fixtures). Postgres is
  runtime state.
- Rate-limit all PokéAPI calls. Never hammer it in tests or CI.

## Python conventions
- Type hints everywhere; mypy strict passes.
- Pydantic models for all request/response schemas. Never return ORM
  objects directly from a route.
- Routers stay thin: parse, call a service function in services/, return.
  No business logic in route handlers.
- async SQLAlchemy with asyncpg. httpx.AsyncClient for outbound calls.
- pytest + pytest-asyncio. Test pure functions properly; don't test the ORM.
- uv for dependency management. Ruff for lint and format.

## Frontend conventions
- Vite + React + TypeScript. TanStack Query for all server state.
- Generate the API client from the FastAPI OpenAPI schema — do not
  hand-write fetch calls or duplicate types.
- @dnd-kit for drag and drop. CSS Grid for the catalog layout.

## Scope discipline
Do only what the current prompt asks. Do not scaffold future phases,
do not add auth, do not add features not requested.