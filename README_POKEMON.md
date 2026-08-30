# Pokémon Team Builder — design overview

- **Live UI** — https://pokemon-team-builder-henna.vercel.app/
- **API / Swagger** — https://pokemon-team-builder-production-ced1.up.railway.app/

FastAPI on Railway, React + Vite on Vercel, Postgres on Neon. Full engineering
detail is in [README.md](README.md); this page is the four decisions worth
defending.

---

## 1. Authentication

Identity is an anonymous UUID generated client-side on first load, kept in
`localStorage`, and sent as `X-User-Id` on every request. That satisfies
cross-session persistence — teams survive a browser close — without an auth
system.

It is deliberately **not a security boundary**. Anyone can send any UUID. The
data is public Pokémon information and there is nothing to protect. The cost is
that teams don't follow a user to another device, which the brief doesn't ask
for. One detail that isn't laziness: another user's team returns **404, not
403** — a 403 confirms the id exists and belongs to someone.

Real accounts are the first production addition, and `app_user` is already the
right shape for it: add `username` and `password_hash`, swap the UUID for an
authenticated id inside `get_current_user`, and nothing downstream changes —
every route already consumes `current_user.id`. Roughly half a day, deferred in
favour of the counter-team algorithm and change detection.

## 2. Database design and management

Postgres, hosted on **Neon**. Serverless Postgres suits a workload that is
bursty and read-heavy, and its connection pooler matters here because the API
runs asyncpg against a pooled endpoint while Alembic connects synchronously over
psycopg — two drivers, one database, which is why the service takes two
connection URLs.

**Snapshot, don't proxy.** PokéAPI is mirrored into Neon rather than called per
request. This wasn't for latency; it's the prerequisite for change detection.
You cannot diff against an API you have no prior copy of.

**Store base stats, derive level 50.** Stats persist exactly as PokéAPI returns
them. Level-50 conversion happens in the derived layer, at read time. Storing
converted values would make every sync compare converted against raw and report
the entire dataset as changed.

**Normalise before hashing.** Payloads are projected down to the fields we
consume and arrays sorted before hashing, because PokéAPI's array ordering is
not stable. Without this the first nightly run reports ~1,300 false changes. The
regression test is a double run: sync twice, expect zero changes the second time.

**Hash by section, not by row.** Separate `stats_hash`, `types_hash`,
`moves_hash`, `sprite_hash`, so an alert can say *Attack 55 → 60* rather than
*Pikachu changed*.

**Allowlist the 18 battle types.** `/type` returns non-battle entries
(`unknown`, `shadow`, `stellar`, and more whenever PokéAPI adds them), so the
chart is built from an explicit allowlist with a 324-row assertion. A blocklist
would break silently on every addition.

**Derived data lives in memory.** Type lookups, defensive vectors and collapsed
movepools are computed at startup, never materialised as tables — they are pure
functions of the reference data, and a second copy is a second thing to keep in
sync. This implies a single uvicorn worker, since invalidation doesn't propagate
across workers.

**Migrations run in the container start command** (`alembic upgrade head &&
uvicorn …`), so deployed schema can never lag deployed code. Fine at one
replica; more would need a dedicated migration job.

## 3. Pokémon assumptions

Level 50, no EVs or IVs, neutral nature, average damage roll. No items,
abilities, weather, status or stat stages. Single-turn evaluation, no switching.
Multi-turn moves (Solar Beam's charge) and self-debuffs (Draco Meteor halving
Sp. Atk) are not modelled. No tier restrictions, so legendaries dominate the
picks — accepted as scope, not filtered.

The exclusions aren't a list of things left undone. **Everything included is
fixed before the battle starts**, so a matchup is a pure function of two Pokémon
and can be computed once at startup. **Everything excluded only has a value
mid-battle**, and modelling any of it means building a turn-by-turn simulator
with mutable state — one feature, not six.

## 4. The counter-team algorithm

Given an opposing team of N Pokémon, return N counters.

1. **Score every candidate against every enemy, both directions.** Damage is
   computed at level 50 for all 1,025 candidates as a share of the defender's
   health bar: 1.38 means one hit is enough, 0.51 means it takes two. Both
   directions are required — dealing 0.6 per turn while taking 1.2 is not a
   counter, it's a casualty.

2. **Let speed change the arithmetic, not just break ties.** If we outspeed and
   KO in N turns, the opponent acts N−1 times. A candidate that moves first and
   one-shots takes *zero* damage, not "some damage, discounted". An earlier
   symmetric version scored a Pokémon that dies before acting as though it had
   traded blows.

3. **Cap overkill at ~1.2 before scoring.** Dealing 355% of a health bar is not
   three times better than 120% — both are one-turn KOs. Uncapped, overkill
   compressed every candidate into a narrow band where the ranking carried
   almost no information.

4. **Never round to a turn count inside the scorer.** `ceil()` collapses damage
   into about four values, producing *more* ties than the type-only score it
   replaced and handing each to iteration order. Rounding is presentation.

5. **Keep a scorecard, one row per enemy**, holding how well the team built so
   far answers it. Everything starts at zero.

6. **Each round, rank candidates by how much they improve the scorecard**, not
   by how good they are alone. A candidate offering 0.85 against an enemy
   already answered at 0.80 is worth 0.05; one offering 0.60 against an enemy
   nothing touches is worth the full 0.60. Take the best, update, repeat.

7. **That update is the entire diversity mechanism.** Rank on raw quality and
   you get six exploits of one shared weakness, which any resistant opponent
   sweeps. Ranking on improvement means a strong pick whose job is already done
   contributes nothing — a second Rock answer to an answered Charizard scores
   zero, not 4.5.

8. **Break ties deterministically:** typings the team lacks, then base stat
   total descending, then id ascending. The last isn't cosmetic — without it
   iteration order decides and tests fail intermittently.

9. **Report turn margin, not the score.** 0.84 vs 0.79 means nothing without the
   formula. The UI shows how many attacks the enemy runs short by — a signed
   integer, so +3 and +1 differ at a glance — collapsing to a verdict
   (Dominates / Wins / Trades / Loses). The continuous score still orders the
   results underneath, because margin is coarse enough that many picks tie.

**No tuning parameter.** An earlier version decayed a per-enemy urgency weight
after each pick. It worked, but introduced a constant we'd have had to justify.
Here diminishing returns falls out of the structure: the objective — sum over
enemies of the best answer on the roster — is monotone and submodular, so greedy
carries the standard (1 − 1/e) bound. Removing the parameter beat tuning it.

Coverage scores each enemy by its single best answer rather than the sum, since
you only need one answer per threat; summing rewards redundancy and recreates
the clustering the algorithm exists to prevent.

Runs in memory off the startup caches: **~4 ms for six Pokémon against 1,025
candidates.**

*Not implemented:* greedy commits early and can't reconsider, so a strong first
pick can foreclose better options. A swap pass would try each slot against the
top alternatives and keep any swap that raises overall coverage.
