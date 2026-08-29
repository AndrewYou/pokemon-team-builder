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
cd api && cp .env.example .env && uv sync && uv run uvicorn app.main:app --reload
```

`GET /health` runs `SELECT 1` and returns `{ok, db}`. It answers `200` even when
the database is down, reporting the failure in the body, so the platform health
check stays green while the frontend can still show *why* it is unreachable.

### Checks

```bash
cd api && uv run ruff check . && uv run mypy app tests && uv run pytest
cd web && npm run build
```

## Environment

| Service | Variable | Notes |
| --- | --- | --- |
| api | `DATABASE_URL` | Neon connection string. A plain `postgresql://…?sslmode=require` URL is accepted and normalized for asyncpg at startup. |
| api | `CORS_ORIGINS` | Comma-separated. Defaults to `*`, which is legal here because `allow_credentials=False`. |
| web | `VITE_API_URL` | Base URL of the API, no trailing slash. Baked in at build time. |

## Deploy

1. **Neon** — create a project, copy the pooled connection string.
2. **Railway** — new project from this repo, root directory `api`, Dockerfile
   builder. Set `DATABASE_URL`. Generate a public domain.
3. **Vercel** — import the repo, root directory `web`. Set `VITE_API_URL` to the
   Railway URL. Deploy.
4. Set `CORS_ORIGINS` on Railway to the Vercel URL and redeploy.
5. Open the Vercel URL and confirm it shows `db: connected`.

`VITE_API_URL` is inlined at build time, so changing it requires a redeploy of
the frontend, not just a restart.
