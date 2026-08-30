# Pokémon Team Builder

**Live UI** — https://pokemon-team-builder-henna.vercel.app/
**Swagger** — https://pokemon-team-builder-production-ced1.up.railway.app/

FastAPI on Railway, React + Vite on Vercel, Postgres on Neon. Full detail in
[README.md](README.md).

## 1. Authentication

An anonymous UUID, client-generated, kept in `localStorage` and sent as
`X-User-Id` — persistence across sessions without an auth system. 

## 2. Database design and management

Postgres on **Neon**.

- **JSON snapshot, not a proxy** — one committed fixture of PokéAPI's 1,025 Pokémon,
  937 moves and 21 types. It seeds and tests; Postgres is runtime state. You cannot
  diff against an API you have no prior copy.
- **Store base stats**, converting to level 50 at read time; otherwise every sync
  reports the whole dataset as changed.
- **Normalise before hashing** — PokéAPI's array order isn't stable; without it the
  first run reports ~1,300 false changes.
- **Hash by section** (`stats`, `types`, `moves`, `sprite`), so alerts say *Attack
  55 → 60*, not *Pikachu changed*.
- **Allowlist the 18 battle types** (324-row chart assertion). Of PokéAPI's 21,
  `stellar` is Terastal-only, `shadow` spin-off-only, `unknown` a placeholder.
- **Derived data in memory** — type lookups, defensive vectors and movepools are
  pure functions of reference data, built at startup.

## 3. Pokémon assumptions

Level 50, no EVs or IVs, neutral nature, average damage roll. No items, abilities,
weather, status, stat stages or switching. No tier restrictions, so legendaries
dominate.

Not omissions: everything included is fixed before the battle starts, so a matchup
is a pure function computable at startup; everything excluded needs mid-battle
state and a simulator to track it.

## 4. The counter-team algorithm

Given N opponents, return N counters — ~4 ms against 1,025 candidates. One hit at
level 50:

```
base     = (22 × power × attack / defense) / 50 + 2      # 22 is the level-50 term
damage   = base × STAB (1.5 on a matching type) × multiplier × accuracy
fraction = damage / defender HP
```

1. **Score all 1,025 candidates against every enemy, both directions.** Dealing
   0.6 per turn while taking 1.2 is a casualty, not a counter.
2. **Speed changes the arithmetic** — outspeed and KO in N turns and they act N−1
   times, so a first-strike one-shot takes zero damage.
3. **Cap overkill at ~1.2** — 355% and 120% are both one-turn KOs; uncapped, it
   flattens the ranking.
4. **Don't round to turns inside the scorer** — `ceil()` collapses damage to four
   values and creates ties.
5. **Keep a scorecard, one row per enemy**, starting at zero.
6. **Rank each round by improvement to it**, not strength: 0.85 against an enemy
   already answered at 0.80 is worth 0.05; 0.60 against an unanswered one is worth
   0.60.
7. **That update is the diversity mechanism** — a pick whose job is done scores
   zero, so you avoid six exploits of one weakness.
8. **Break ties deterministically:** typings the team lacks, then stat total, then
   id.
9. **Report turn margin, not the score** — how many attacks the enemy runs short
   by: Dominates / Wins / Trades / Loses.
