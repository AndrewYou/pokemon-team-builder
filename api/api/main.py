"""FastAPI application entrypoint.

Swagger is the primary demo surface for this project, so the OpenAPI metadata
here is load-bearing rather than decoration: the tag groups below are what give
/docs a readable shape as later phases add routers.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from api.config import settings
from api.db import SessionLocal
from api.derived import registry
from api.routers import admin, catalog, counterteam, health, sync, syncruns, teams

logger = logging.getLogger(__name__)

DESCRIPTION = """
A Pokemon team builder over a local snapshot of [PokeAPI](https://pokeapi.co).

**Everything here is runnable from this page.** Long jobs return `202` with a
`poll_url` instead of blocking, so nothing hangs the browser.

### Getting started
1. `POST /admin/seed?source=fixture` -- loads the committed snapshot in seconds.
2. `GET /admin/jobs/{id}` -- follow the job to completion.
3. `GET /admin/stats` -- watch the row counts fill in.

Admin routes use HTTP Basic (`admin` / `pokemon` by default). This is
presentation hygiene, not a security boundary: the data is public and there is
no user authentication. These docs stay open to everyone.

### Declared simplifications
Level 50, no EVs or IVs, neutral nature, average damage roll. Base stats are
stored exactly as PokeAPI returns them; level-50 conversion happens in the
derived layer so that change detection compares like with like.
"""

# Tag order here is the order of sections in Swagger. Groups for later phases
# are declared up front so the page reads as a roadmap rather than a surprise.
OPENAPI_TAGS = [
    {
        "name": "admin",
        "description": (
            "Operational jobs: seeding, and the row counts that show them working. "
            "HTTP Basic protected so a stray click cannot start a crawl."
        ),
    },
    {
        "name": "catalog",
        "description": "Browse and filter the Pokemon catalog. Added in a later phase.",
    },
    {
        "name": "teams",
        "description": "Create and edit teams of up to six Pokemon. Added in a later phase.",
    },
    {
        "name": "counter-team",
        "description": "Suggest a team that counters a given one. Added in a later phase.",
    },
    {
        "name": "alerts",
        "description": (
            "Upstream changes affecting your teams, and acknowledging them. Added in a later phase."
        ),
    },
    {
        "name": "health",
        "description": "Liveness and database connectivity.",
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Build the derived layer once, at startup.

    Failure is tolerated on purpose. A fresh deployment has an empty database,
    and refusing to start would make the API unbrowsable exactly when someone is
    trying to seed it. The endpoints that need the cache answer 503 with the two
    calls that fix it.
    """
    async with SessionLocal() as session:
        await registry.ensure_built(session)
    yield


app = FastAPI(
    title="Pokémon Team Builder API",
    version="0.1.0",
    description=DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "Source", "url": "https://github.com/AndrewYou/pokemon-team-builder"},
    lifespan=lifespan,
)

# allow_credentials is False, so the wildcard default is legal: the browser will
# not attach cookies or Authorization headers to these requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser hides the header from cross-origin JavaScript, so
    # a client that let the API mint its identity could never read it back.
    expose_headers=["X-User-Id"],
)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(teams.router)
app.include_router(counterteam.router)
app.include_router(syncruns.router)
app.include_router(sync.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send the bare Railway URL somewhere useful instead of a 404."""
    return RedirectResponse(url="/docs")
