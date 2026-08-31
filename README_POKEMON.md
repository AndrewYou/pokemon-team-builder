# Pokémon Team Builder

**Live UI** — https://pokemon-team-builder-henna.vercel.app/
**Swagger** — https://pokemon-team-builder-production-ced1.up.railway.app/

FastAPI on Railway, React + Vite on Vercel, Postgres on Neon. Full detail in
[README.md](README.md).

## 1. Authentication

An anonymous UUID, client-generated, kept in `localStorage` and sent as `X-User-Id`
— persistence across sessions without an auth system.

## 2. Database design and management

Postgres on **Neon**.

- **JSON snapshot** — one committed fixture of PokéAPI's 1,025 Pokémon, 937 moves
  and 21 types. Seeds Postgres without calling PokéAPI. Postgres then serves every
  request and holds the prior copy each sync diffs against.
- **Store raw base stats exactly as PokéAPI returns them** — Storing converted
  values would make every sync compare converted against raw and report the whole
  dataset as changed.
- **Sorting before hashing** — PokéAPI's array order isn't stable; without it the
  first run reports 1,025 false changes.
- **Hash by section** (`stats`, `types`, `moves`, `sprite`), so alerts say *Attack
  55 → 60*, not *Pikachu changed*.
- **Allowlist the 18 battle types** (324-row chart assertion). Of PokéAPI's 21,
  `stellar` is Terastal-only, `shadow` spin-off-only, `unknown` a placeholder.
- **Derived data in memory** — type lookups, defensive vectors and movepools are
  pure functions of reference data, built at startup.

## 3. Pokémon assumptions

Level 50, no EVs or IVs, neutral nature, average damage roll. No items, abilities,
weather, status, stat stages or switching.

No tier restrictions, so legendaries dominate.

Everything modelled — stats, types, moves, speed — is known before the battle
starts, so a matchup is a pure function of two Pokémon. Everything excluded changes
as the battle unfolds, which would require simulating turns. We don't.

## 4. The counter-team algorithm

Given N opponents, return N counters. One hit at level 50 is measured as follows:

```
base     = (22 × power × attack / defense) / 50 + 2   # 22 is the level-50 term
damage   = base × STAB (1.5 on a matching type) × multiplier × accuracy
fraction = damage / defender HP                       # 1.0 = a one-turn KO
```

1. **Score every candidate against every enemy, both directions.** The score
   combines outgoing fraction, incoming fraction and speed into one 0–1 value.
   Dealing 0.6 per turn while taking 1.2 is a casualty, not a counter.
2. **Speed decides who acts first** — if the counter outspeeds and KOs in N turns,
   the opponent acts only N−1 times, so a first-strike one-shot takes nothing back.
3. **Cap the outgoing fraction at ~1.2** — anything past a one-turn KO is wasted, so
   355% and 120% score the same.
4. **Never round inside the scorer.** `ceil(1 / fraction)` gives whole turns to KO,
   which collapses 1,025 candidates into a handful of buckets and ties constantly.
   Rounding is a display concern.
5. **Keep a scorecard: N rows, one per opponent, each holding one number** — the
   highest score any pick so far achieves against it. Six opponents means six
   values, all starting at zero.
6. **Each round, rank candidates by improvement to the scorecard, not raw
   strength.** For a candidate, take its score against each opponent, subtract what
   the scorecard already holds, keep only the gains, and sum them. Highest total
   wins the slot. Scoring 0.85 against an opponent already answered at 0.80 is worth
   0.05; 0.60 against an unanswered one is worth the full 0.60.
7. **Updating the scorecard after each pick is what forces diversity.** Once a pick
   answers Charizard at 0.82, every remaining Charizard counter offers near-zero
   improvement — however strong it is in isolation. Rank on raw score instead and
   all six picks exploit whatever weakness the opposing team shares, leaving you
   swept by anything that resists it.
8. **Break ties deterministically:** typings the team lacks, then stat total, then
   id.
9. **Report turn margin, not the score.** 0.84 vs 0.79 means nothing to a reader, so
   the UI shows how many turns the opponent falls short by — `ceil(1/fraction)` each
   way, adjusted for speed — as Dominates / Wins / Trades / Loses.
