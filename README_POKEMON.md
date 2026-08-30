# Design decisions

Four things worth knowing before reading the code: how identity works, why the
data is shaped the way it is, what the battle model assumes, and how the
counter-team algorithm actually picks.

## Authentication

Identity is an anonymous UUID generated client-side on first load, stored in
`localStorage`, and sent as `X-User-Id` on every request. This satisfies the
cross-session persistence requirement — teams survive a browser close and
reload — without an authentication system.

It is deliberately **not a security boundary**. Anyone can send any UUID. The
data is public Pokémon information and there is nothing to protect. The tradeoff
is that teams do not follow a user to another browser or device, which the brief
does not require.

Real accounts are the first production addition, and `app_user` is already the
right shape for it: add `username` and `password_hash`, swap the UUID for an
authenticated id inside `get_current_user`, and nothing downstream changes —
every route already consumes `current_user.id`. Roughly half a day, deferred in
favour of the counter-team algorithm and change detection.

## Data design and management

**Snapshot over proxy.** PokéAPI is mirrored into Postgres rather than proxied
per request. Caching was not for performance; it is the prerequisite for change
detection. You cannot diff against an API you have no prior copy of.

**Base stats stored, level 50 derived.** Stats persist exactly as PokéAPI
returns them, and level-50 conversion happens in the derived layer. Storing
converted values would make every sync compare converted against raw and report
the entire dataset as changed.

**Normalisation before hashing.** Payloads are projected down to the fields we
consume and arrays sorted before hashing, because PokéAPI's array ordering is
not stable. Without this the first nightly run reports ~1,300 false changes. The
double-run test — sync twice, expect zero changes the second time — is the
assertion that protects it.

**Section hashes, not row hashes.** Separate `stats_hash`, `types_hash`,
`moves_hash` and `sprite_hash`, so an alert can say *Attack 55 → 60* rather than
*Pikachu changed*.

**Type allowlist, not a blocklist.** `/type` returns non-battle entries
(`unknown`, `shadow`, `stellar`, and possibly more later), so the chart is built
from an explicit 18-type allowlist with a 324-row assertion. A blocklist breaks
silently every time PokéAPI adds an entry.

**Derived data lives in memory.** Type lookups, defensive vectors and collapsed
movepools are computed at startup rather than materialised as tables — they are
pure functions of the reference data, and a second copy is a second thing to
keep in sync. This implies a single uvicorn worker, since invalidation does not
propagate across workers.

**Migrations in the container start command.** `alembic upgrade head && uvicorn
…`, so the deployed schema can never lag the deployed code. Fine at one replica;
more would need a dedicated migration job.

## Pokémon assumptions

Level 50, no EVs or IVs, neutral nature, average damage roll. No items,
abilities, weather, status or stat stages. Single-turn evaluation, no switching.
Multi-turn moves (Solar Beam's charge) and self-debuffs (Draco Meteor halving
Sp. Atk) are not modelled. No tier restrictions, so legendary Pokémon dominate
the picks — accepted as scope rather than filtered.

The line is not arbitrary: **everything excluded requires battle state;
everything included is a static property of the matchup.** That distinction is
the architectural boundary, and it is why the excluded items are omissions of
scope rather than gaps in the model.

## The counter-team algorithm

Given an opposing team of N Pokémon, we return N counters.

1. **Score every candidate against every enemy, in both directions.** Damage is
   computed at level 50 for all ~1,025 candidates and expressed as a fraction of
   the defender's HP: 1.38 is a one-turn knockout with margin, 0.51 is two
   turns. Both directions are required — a candidate dealing 0.6 per turn while
   taking 1.2 is not a counter, it is a casualty.

2. **Let turn order change the arithmetic, not just break ties.** If we outspeed
   and knock out in N turns, the opponent acts N−1 times, not N. So a candidate
   that moves first and one-shots takes *zero* damage, not "some damage,
   discounted". We compute the defender's actual turn count and multiply
   incoming damage by it. An earlier symmetric version scored a Pokémon that
   dies before acting as though it had traded blows.

3. **Clamp overkill at ~1.2 before scoring.** Dealing 355% of a health bar is
   not three times better than dealing 120% — both are a one-turn knockout.
   Uncapped, overkill compressed every candidate into a narrow band where the
   ranking carried almost no information.

4. **Never round to a turn count inside the scorer.** `ceil()` collapses damage
   into about four values, producing *more* ties than the coarse type-only score
   it replaced and handing each one to iteration order. Rounding is a
   presentation concern and happens at the presentation layer.

5. **Keep a scorecard, one line per enemy**, recording how well the team we are
   building answers it so far. Everything starts at zero.

6. **Each round, rank candidates by how much they improve the scorecard** — not
   by how good they are in isolation. A candidate offering 0.85 against an enemy
   already answered at 0.80 is worth 0.05; one offering 0.60 against an enemy
   nothing touches is worth the full 0.60. Take the highest, update the
   scorecard, repeat until the team is full.

7. **That update is the entire diversity mechanism.** Rank on raw quality and
   you get six exploits of one shared weakness, which any opponent resistant to
   it sweeps. Ranking on improvement means a strong pick whose job is already
   done contributes nothing — a second Rock type against an already-answered
   Charizard scores zero, not 4.5.

8. **Break ties deterministically:** typings the team does not yet have, then
   base stat total descending, then id ascending. The last is not cosmetic —
   without it iteration order decides, and tests fail intermittently. The type
   term matters most when a round *saturates*: against three Fire types one good
   Rock answer covers all three, every remaining candidate gains zero, and
   ranking those by raw score returns three near-identical Pokémon.

9. **Report turn margin, not the score.** 0.84 versus 0.79 means nothing to a
   person without the formula. The UI shows how many turns to spare we win the
   exchange by, counting who moves first — a signed integer, so +3 and +1 differ
   at a glance — and degrades to a verdict (Dominates / Wins / Trades / Loses)
   for scanning. The continuous score still decides ordering underneath, because
   margin is coarse enough that many picks tie on it.

**No tuning parameter.** An earlier version decayed a per-enemy urgency weight
after each pick. It worked, but introduced a constant we would have had to
justify. In the marginal-gain form, diminishing returns falls out of the
structure instead. The objective — sum over enemies of the best answer on the
roster — is monotone and submodular, so greedy selection carries the standard
(1 − 1/e) bound on how far from optimal it can land. Removing the parameter beat
tuning it.

Coverage scores each enemy by the single best answer on the roster rather than
the sum, because you only need one answer per threat; summing rewards redundancy
and recreates the clustering the algorithm exists to prevent.

The whole thing runs in memory against the startup-derived caches: **~4 ms for a
six-Pokémon team against 1,025 candidates.**

*Next refinement, not yet implemented:* greedy commits early and cannot
reconsider, so a strong first pick can foreclose better options later. A swap
pass would try each slot against the top alternatives and keep any swap that
raises overall coverage.
