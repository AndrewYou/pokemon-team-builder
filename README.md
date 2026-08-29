# Pokémon Team Builder

Monorepo. `/api` is a FastAPI service, `/web` is a Vite + React frontend.

Deployment is wired up before any feature work: two services mean CORS, env
vars, and two pipelines, and all of those are cheaper to debug on day one.

## Layout

```
api/   FastAPI, SQLAlchemy 2.0 async, Alembic  -> Railway (Dockerfile)
web/   Vite + React + TS + Tailwind + shadcn/ui -> Vercel
```

## Local development

Requires [uv](https://docs.astral.sh/uv/), Node 20+, and Docker.

```bash
# Postgres + API together
docker compose up --build          # API on :8000

# Frontend
cd web && cp .env.example .env && npm install && npm run dev   # :5173
```

To run the API without Docker, start Postgres yourself and:

```bash
cd api && cp .env.example .env && uv sync
uv run alembic upgrade head
uv run uvicorn api.main:app --reload
```

Keep `api/.env` pointed at a local database. Alembic reads it, so a `.env`
holding production credentials turns `alembic downgrade` into a production
outage. Environment variables override `.env` if you need to target another
database for a single command.

The frontend serves the app at `/` and the connectivity check at `/health`;
`vercel.json` adds the SPA rewrite that keeps a hard refresh on `/health` from
404ing.

`GET /health` runs `SELECT 1` and returns `{ok, db}`. It answers `200` even when
the database is down, reporting the failure in the body, so the platform health
check stays green while the frontend can still show *why* it is unreachable.

### Checks

```bash
cd api && uv run ruff check . && uv run mypy api tests && uv run pytest
cd web && npm run build
```

## Seeding

```bash
make migrate     # apply Alembic migrations first
make seed        # from the committed fixture, offline (default)
make seed-live   # from pokeapi.co: ~2,300 rate-limited requests, minutes
make fixture     # regenerate fixtures/pokeapi-snapshot.json from pokeapi.co
```

`make seed` is the fixture path on purpose, so a stray invocation can never
hammer PokeAPI. Seeding is idempotent: every write is an upsert keyed on the
natural primary key, so re-running converges instead of duplicating.

Both targets write to whatever `DATABASE_URL` names, including production if
that is what `api/.env` holds. Prefix with an explicit URL when in doubt:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/pokemon make seed
```

### Fixture payloads are trimmed

A faithful copy of every payload would be roughly 400 MB, over 90% of it
`version_group_details` -- per-move, per-game learn data we never read. The
snapshot stores only the fields this project persists, which brings it to about
20 MB. The trim is idempotent and a test asserts that seeding from the fixture
produces byte-identical rows to seeding live. The tradeoff is real: `raw` can
only backfill columns derivable from what survived the trim.

### Failures are never silent

A seed that quietly dropped a third of its movepools would look exactly like a
successful one until the counter-team endpoint had nothing to choose from. Fetch
failures and per-record normalisation errors are collected, printed in full, and
turned into a non-zero exit code. The fixture writer goes further and refuses to
write a partial snapshot at all.

## Environment

| Service | Variable | Notes |
| --- | --- | --- |
| api | `DATABASE_URL` | `postgresql+asyncpg://…` — the application. |
| api | `ALEMBIC_DATABASE_URL` | `postgresql+psycopg://…` — migrations. |
| api | `CORS_ORIGINS` | Comma-separated. Defaults to `*`, legal because `allow_credentials=False`. |
| web | `VITE_API_URL` | Base URL of the API, no trailing slash. Baked in at build time. |

### Why two database URLs

Same database, two drivers, because the app is async and Alembic is not.

- **`+asyncpg` is not optional.** Without the driver marker SQLAlchemy reaches
  for psycopg2, which is not installed, and fails on import.
- **asyncpg does not understand `?sslmode=require`.** It is a libpq parameter;
  asyncpg raises `TypeError` on the unexpected connect kwarg. It is stripped
  from `DATABASE_URL` and re-applied as `connect_args={"ssl": "require"}`.
- **Alembic runs synchronously** on `postgresql+psycopg://`. psycopg is
  libpq-based and reads `sslmode` natively, so that URL is passed through as-is.
  A separate variable is simpler than an async Alembic environment.

## Deploy

1. **Neon** — create a project, copy the pooled connection string.
2. **Railway** — new project from this repo, root directory `api`, Dockerfile
   builder. Set `DATABASE_URL` and `ALEMBIC_DATABASE_URL`. Generate a public
   domain. The container binds `0.0.0.0:$PORT`, which Railway injects.
3. **Vercel** — import the repo, root directory `web`. Set `VITE_API_URL` to the
   Railway URL. Deploy.
4. Set `CORS_ORIGINS` on Railway to the Vercel URL and redeploy.
5. Open the Vercel URL and confirm it shows `db: connected`.

`VITE_API_URL` is inlined at build time, so changing it requires a redeploy of
the frontend, not just a restart.
