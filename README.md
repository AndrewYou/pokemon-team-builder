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
cd api && make check
cd web && npm run build
```

## Swagger is the demo surface

`/` redirects to `/docs`. Everything is runnable from that page; no curl needed.

1. `POST /admin/seed?source=fixture` -- returns `202` with a `poll_url`
2. `GET /admin/jobs/{id}` -- follow it to completion
3. `GET /admin/stats` -- re-run to watch the row counts fill in

Admin routes use HTTP Basic, defaulting to `admin` / `pokemon`
(`ADMIN_USERNAME` / `ADMIN_PASSWORD`). `/docs`, `/redoc` and `/openapi.json`
are deliberately open so the API can be browsed without credentials.

Long jobs never run inside the request. A multi-minute seed would hang the
Swagger page and could hit a proxy timeout mid-demo, so admin jobs record a row
in `job`, hand off to a background task, and answer `202` immediately. Starting
a second job of a kind already running returns `409`, guarded by a partial
unique index rather than by an application check alone.

`GET /admin/stats` also reports data-quality checks. A Pokemon with a null
sprite renders as a blank tile in the catalog, and noticing that here is far
cheaper than noticing it during a demo. Two of the three conditions are
currently impossible by construction -- `type1` and `raw` are `NOT NULL` -- so
they guard against schema drift rather than against today's data.

## Derived layer

Type lookups, defensive vectors, and later the best-move lists are computed at
startup and held in memory. They are never materialised as tables.

A defensive vector is 18 floats: how a Pokemon takes damage from each attacking
type, with dual typing already multiplied in. Charizard (fire/flying) takes
`2.0 * 2.0 = 4.0` from rock and `0.5 * 0.5 = 0.25` from grass. Immunity wins
outright, so ground is `2.0 * 0.0 = 0.0` despite fire's weakness to it. They are
stored as a single numpy array of shape `[pokemon, 18]` with a
`pokemon_id -> row` map, so scoring a whole catalog later is one vectorised
operation rather than a Python loop.

```
POST /admin/derive-types     write the 324-row chart, returns the distribution
POST /admin/cache/rebuild    recompute the derived layer, returns timing
GET  /admin/debug/matchup    ?attacking_type=rock&pokemon_id=6 -> 4.0, explained
GET  /admin/debug/vector/6   all 18 multipliers for one Pokemon
```

`GET /admin/stats` reports the chart's multiplier distribution and an
`all_values_legal` flag, so the health of this whole phase is one call.

### The cache refreshes itself

Nothing routine requires calling `/admin/cache/rebuild`. It is rebuilt at
startup, so a deploy needs no intervention, and both writers of reference data
-- the seed job and `derive-types` -- rebuild it after they finish. The endpoint
remains as a manual escape hatch.

This matters because a stale derived layer does not fail, it answers
confidently wrong. Defensive vectors are precomputed, while the debug endpoints
read a Pokemon's types live from the database, so a Pokemon whose typing changed
reports its new types beside its old multipliers in the same response: types
`[fire, flying]` with `ground: 2.0`, describing a flying type that is not immune
to ground.

If a rebuild fails, the cache is invalidated rather than left in place. Unbuilt
answers 503 naming the call that fixes it; stale is silently wrong.

### Single worker, by design

The cache is a module-level singleton in process memory. Under multiple uvicorn
workers each process would hold its own copy, and `invalidate()` would only
affect the process that served the request, leaving the others silently stale.
The container therefore runs **one worker** -- uvicorn's default, with no
`--workers` flag in the Dockerfile.

Scaling out would mean giving up the pure in-memory approach: write a version
stamp in Postgres when reference data changes and have each worker re-check it
on a cheap interval, rebuilding when it moves.

### The chart checks its own work

Both write paths -- the seed and `POST /admin/derive-types` -- assert the result
is exactly the known chart before storing it: 324 rows with the distribution
`0 -> 8, 0.5 -> 61, 1 -> 204, 2 -> 51`, confirmed against pokemondb.net/type.

A merely plausible chart is the worst outcome here, because every damage number
downstream would be wrong and nothing in the consuming code would notice. The
two realistic ways to produce one are guarded explicitly:

- **`damage_relations`, never `past_damage_relations`.** The latter holds
  superseded generation-specific charts (Gen 1 had bug 2x into poison, ice 1x
  into fire, ghost 0x into psychic). It is dropped at trim time so it cannot be
  read by accident, and flipping even one relation moves the distribution and
  fails the assertion.
- **The 18 battle types are allowlisted, not the extras blocklisted.** `/type`
  already returns more than 18, and PokeAPI may add more. A blocklist breaks
  silently the moment one appears: 19 types writes 361 rows and 20 writes 400,
  both plausible-looking numbers. The allowlist is a module-level `frozenset`
  whose length is asserted at import, so a new upstream entry needs no code
  change to stay excluded.

`stellar` is excluded on semantics rather than convenience: it is a Terastal
mechanic, its effectiveness is special-cased against Terastallized Pokemon only,
and no species carries it as `type1` or `type2` -- a claim a test checks against
the committed snapshot rather than assuming.

### Why the type list is both a tuple and a frozenset

The `frozenset` is the allowlist, used for membership. The ordered tuple defines
the column layout of every defensive vector and of `TYPE_INDEX`, and it follows
PokeAPI type ids 1 through 18 so a column can be traced back to a real resource.

The two cannot be collapsed. Python hash-randomises strings, so iterating a
`frozenset` yields a different order in every process; deriving the column layout
from it would make `vectors[:, 3]` mean a different type after each restart,
silently invalidating every comparison. The ordering is pinned by a test.

### An incomplete chart refuses to serve

`build_chart` fills unlisted pairings with 1.0, which is right when PokeAPI
omits an exception but wrong if the table is empty -- every matchup would return
a confident, neutral, incorrect 1.0. The cache tracks how many rows it actually
loaded, and the debug endpoints answer 503 with the two calls that fix it rather
than serving from a defaulted chart.

## Alerts

`GET /alerts` answers one question: what changed upstream that affects a team I
built? Changes from the last 7 days, on Pokemon in the caller's teams, minus
anything they have dismissed.

Grouped by Pokemon, because the join multiplies: a change to a Pokemon sitting
on three of your teams comes back as three rows, and showing that alert three
times would be the obvious bug. One group names all three teams.

Descriptions are sentences rather than diffs -- "Pikachu's Attack changed from
55 to 60" -- rendered by the same function the simulator uses to predict them.

`POST /alerts/{id}/dismiss` is idempotent. Re-dismissing answers 200 with the
original timestamp rather than failing on the composite key: a client retrying a
request it already made has not done anything wrong. Dismissals are per user, so
silencing an alert silences it for you alone.

Aging out is not deletion. `POST /admin/age-change/{id}?days=8` backdates a
change so the window can be demonstrated without waiting a week: it leaves
`/alerts` while remaining in `/admin/changes`, which is the line between news
and history.

## Identity: a header, and why that is enough

There is no login. A client sends `X-User-Id`, an opaque UUID, and owns whatever
it created under that UUID. Omit the header and the API mints one, returning it
in the `X-User-Id` response header for the client to store.

**Assumption, stated rather than hidden:** this is trivially spoofable. Anyone
can send someone else's UUID and read their teams. That is acceptable here
because nothing stored is private or valuable -- a list of Pokemon names -- and
adding real authentication would be scope this take-home does not ask for.

A header rather than a cookie because the frontend and API sit on different
origins, and cross-origin cookies mean credentialed CORS, which means giving up
the wildcard origin for no benefit. The header is declared explicitly on every
user-scoped route so it appears in the OpenAPI schema; read off the raw request
instead, Swagger's "Try it out" would not send it and every call would 422.

Another user's team returns **404, not 403**. A 403 would confirm the id exists
and belongs to somebody.

## Application routers

**Catalog** (`/pokemon`) is cursor-paginated, not offset: the frontend scrolls
infinitely, and an OFFSET both slows down as it grows and can skip or repeat
rows if the data shifts mid-scroll. The cursor is an opaque `(sort key, id)`
pair, with the id included so the ordering is total.

Search is a lowercased prefix `LIKE`, which the `text_pattern_ops` index serves.
`ILIKE` would read more naturally and cannot use that index -- it plans a
sequential scan. Stored names are all lowercase, so lowering the search term
gives case-insensitivity and index usage at once. `GET /admin/debug/explain`
shows the plan for each query so this stays checkable rather than assumed.

**Teams** (`/teams`) replaces the whole roster in one request. There are no
add, remove, or move endpoints: a drag-and-drop reorder produces an entirely
new ordering, so sending the array is simpler and atomic. It also sidesteps the
`UNIQUE(team_id, slot)` constraint, which a partial reorder would trip while
swapping two slots.

**Counter-team** (`/counter-team`) is type effectiveness only -- no damage
formula, stats, moves, or speed. One scoring function is the only thing a later
damage model replaces:

```
offense = best multiplier the pick's types land on the enemy
defense = 1 / worst multiplier the enemy's types land back
score   = offense * defense
```

Picks are chosen over six rounds by marginal gain: each round takes whichever
candidate most improves the currently worst-covered enemies. Diminishing returns
come from that structure, not a decay parameter -- once an enemy is answered,
answering it again adds nothing. If coverage saturates before six picks, the
roster is filled by total score rather than returned short.

Immunity is capped rather than infinite: a pick that takes nothing from the
enemy would be a division by zero, so it scores one step above the best
resistance. It is stateless and never touches the database -- the display fields
it needs live in the derived cache.

## The change-detection demo

```bash
cd api
uv run python -m api.sync.run --source stale     # replays our own data: must find 0
```

Or from Swagger, in four calls:

1. `GET /admin/drift` — nothing outstanding
2. `POST /admin/simulate-change` with
   `{"pokemon_ids":[25,6],"fields":["stats","types","sprite"],"mutations_per_field":2}`
   — returns 10 mutations and the exact alert text each will produce
3. `POST /admin/sync?source=fixture` — 202, poll the job
4. `GET /admin/changes` — 10 rows whose messages match `expect_alert` verbatim

`GET /admin/sync-runs` is the run log. A run recording 1025 records scanned and
**0 changes found** is the evidence that this detects changes rather than
inventing them, so both outcomes appear in its response examples.

`POST /admin/reset-demo` clears `change_ack`, `data_change`, and `sync_run` in
one transaction so the sequence can be rehearsed without earlier runs piling up.
Add `restore_snapshot=true` to also run a fixture seed, clearing any outstanding
drift in the same call -- a seed rather than a sync, because a sync would write a
fresh run and a change per repair, which is the noise being removed. **Teams are
never deleted**, whatever the parameters say.

It deletes rather than truncates. `TRUNCATE` does not follow `ON DELETE CASCADE`
and refuses outright while `change_ack` references `data_change`. Children are
deleted first for a second reason: removing `data_change` first would cascade the
acks away silently and report zero for a table that had rows in it.

Every operational read sits behind the same admin gate. Sync runs are global
system state -- there is no per-user scoping on `sync_run` -- so splitting the
aggregate out as public while keeping the field-level detail in `/admin/changes`
would have been an arbitrary line. The admin credentials are published in the
API description, so the gate costs a reviewer one click and hides nothing.

### simulate-change mutates OUR snapshot

It cannot touch PokeAPI; upstream is read-only to us. It edits our stored copy
so the next sync has something real to find, and the sync then writes the true
values back -- which is why there is no reset endpoint.

**The inversion catches everyone.** If Attack is 55 upstream and we mutate our
copy to 71, the sync reports 71 -> 55: `old_value` is what we mutated to,
`new_value` is the truth.

Two failure modes it is built to avoid. Mutating only the hash would leave the
sync detecting a mismatch, diffing raw against upstream, finding nothing, and
silently repairing the hash -- a false negative that looks like a broken
detector. So the raw payload is what changes, and the row is rebuilt from it
wholesale via `pokemon_row`, which is also why mutating stats and types together
moves *both* section hashes: no hash is updated by hand, so none can be missed.

### Sync

Records are committed in batches, so a failure at record 800 keeps the first
799 findings rather than rolling back a run that took minutes. `POST /admin/sync`
accepts **either** HTTP Basic or an `X-Cron-Secret` header, because a scheduled
job cannot answer a browser password prompt and a reviewer should not need a
shared secret. A second concurrent sync returns 409.

## Normalisation and change detection

`api/sync/` holds the projection, the section hashes, and the diff. It is the
most bug-prone code here, and its failure mode is a false positive rather than
a crash: hashing a raw payload reports a change on every single run, because
PokeAPI does not guarantee array ordering and most of the payload is fields we
never read. A change feed that flags everything is worse than none, because
nobody can tell which entries are real.

`normalize_pokemon` projects a payload down to consumed fields and gives every
collection a stable order. Movepools are sorted and deduplicated, abilities
become a mapping, and type slots keep their order because slot 1 and slot 2 are
different facts. Everything downstream operates on the projection.

Hashes are per section -- `stats`, `types`, `moves`, `sprite` -- not one row
hash, which is what lets a change be reported as "Attack 84 -> 90" rather than
"Charizard changed somehow". A stat change moves only `stats_hash`; tests pin
that isolation.

`diff(old_raw, new_raw)` normalises both sides and walks the result, emitting
`(field_path, old_value, new_value, change_type)`. Movepools diff as sets, so
learning a low-numbered move is one addition rather than a cascade of index
shifts through every later entry.

```
GET  /admin/debug/normalize/{id}      raw and projection side by side
POST /admin/debug/determinism-check   re-hash every Pokemon against the database
```

The suite for this layer:

```bash
cd api && uv run pytest tests/test_normalize.py tests/test_hashing.py -v
```

The determinism check is what protects the whole change-detection demo: if
normalisation is not a pure function of the stored payload, the next sync
reports every Pokemon as changed. It compares 4,100 stored hashes in about
110 ms, and any non-zero result is a bug rather than a data change.

## Seeding

All `make` targets live in `api/` and run from there:

```bash
cd api
make migrate     # apply Alembic migrations first
make seed        # from the committed fixture, offline (default)
make seed-live   # from pokeapi.co: ~2,300 rate-limited requests, minutes
make fixture     # regenerate fixtures/pokeapi-snapshot.json from pokeapi.co
make check       # lint, typecheck, test
```

`make seed` is the fixture path on purpose, so a stray invocation can never
hammer PokeAPI. Seeding is idempotent: every write is an upsert keyed on the
natural primary key, so re-running converges instead of duplicating.

Both targets write to whatever `DATABASE_URL` names, including production if
that is what `api/.env` holds. Prefix with an explicit URL when in doubt:

The seed prints the host and database it is about to write to before it writes.

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
| api | `ALEMBIC_DATABASE_URL` | `postgresql+psycopg://…` — migrations. Optional: derived from `DATABASE_URL` when unset. |
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

### Migrations run on deploy

The container runs `alembic upgrade head` before starting uvicorn, so a deploy
that adds a table cannot leave the API answering 500s against an older schema.
If the migration fails the container deliberately does not come up, rather than
serving a half-migrated database.

Only `DATABASE_URL` needs to be configured on the platform: Alembic derives its
own psycopg URL from it when `ALEMBIC_DATABASE_URL` is unset.
