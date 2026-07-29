# API-Football ingestion + multi-vendor directory reshape

**Date:** 2026-07-29
**Status:** Phase 0 executed 2026-07-29 — findings below, plan updated to match.
Phases 1–4 not yet started.

> **Phase 0 result (see `logbook/apifootball.md`, 2026-07-29):** Pro confirmed
> at **7,500/day, 300/min**. API-Football **does** expose pre-2024 domestic
> injury history — **11 leagues carry 2020–2025**, which Sportmonks
> structurally cannot provide. The "breadth, not history" risk below did **not**
> materialise. Measured spine cost: **103 league-seasons**, not ~130.

Adds a second vendor (API-Football) alongside Sportmonks, and reshapes the tree
so two — eventually more — vendors coexist without their scripts, caches and
reference files bleeding into each other.

Decisions taken before writing this (see "Decisions" at the bottom for the
reasoning): **Pro plan (7,500/day)**, **spine + season aggregates** (no
per-fixture enrichment), **full reshape of both vendors**, **separate database**.

---

## Why a second vendor at all

Not redundancy — the two APIs have opposite shapes, and each covers the other's
hard limit:

| | Sportmonks | API-Football |
|---|---|---|
| Injuries | No endpoint. Reconstructed from `sidelined` riding on fixtures | **Direct `/injuries?league&season`** |
| Fixture granularity | One call per league **month** | One call per league **season** |
| Rate limit | Per-entity rolling-hour buckets | Global **daily quota + ~10/min** |
| Coverage discovery | None — we scraped their marketing page | **`coverage.injuries` flag per league-season** |
| Domestic history | **Hard-capped at 3 seasons** (2024/25+) | Unknown; measured below |

The Sportmonks domestic cap (logbook 2026-07-27) is not a fetching problem and
cannot be paid around on that plan. If API-Football exposes older domestic
seasons, it is the only route to history we have. If it doesn't, we learn that
in ~130 calls and stop.

Second, independent value: **a cross-vendor check on injury records.** Two
vendors disagreeing about whether a player was injured is a data-quality signal
neither can give alone.

---

## The cost calculation that sets the scope

At Pro (7,500 calls/day, ~300/min):

| Layer | Calls | Notes |
|---|---|---|
| `/status`, `/countries`, `/leagues` | ~3 | `/leagues` carries every season + coverage flag |
| `/teams` per league-season | ~130 | 43 covered leagues x 3 seasons |
| `/fixtures` per league-season | ~130 | paginated; budget ~2x |
| **`/injuries` per league-season** | **~130** | the spine |
| `/standings` per league-season | ~130 | in scope |
| `/teams/statistics` per team-season | ~2,600 | ~20 teams x 130 league-seasons |
| **Spine + aggregates total** | **~3,200** | **under one day of Pro quota** |
| *(excluded)* per-fixture events/lineups/players/stats | *~128,000* | 4 calls x ~32,000 fixtures |

Per-fixture enrichment is ~40x the entire rest of the crawl and is **out of
scope**. The runners are structured so it can be switched on later without
rework, but nothing in this plan fetches it.

---

## Phase 0 — Recon before writing any runner

Three calls, and they can invalidate the rest of the plan. Do not skip.

1. **`GET /status`** — authoritative plan, daily limit, and calls used today.
   Confirms Pro is active and tells the pacer the real ceiling instead of a
   hardcoded guess.
2. **`GET /leagues`** — one call returns every league, every season, and the
   per-season `coverage` object. Cache it; it is the crawl's work list.
3. **Season-depth read** — from that same cached response, for each of the 55
   UEFA top-tier leagues, list the seasons where `coverage.injuries` is true.

**The question Phase 0 answers:** does API-Football expose domestic seasons
older than 2024? Our earlier probe (this repo, run 6) found only 11 leagues with
2023+2024 injury coverage and ~32 that appear to start at 2025. If that holds,
API-Football adds **breadth, not history**, and the honest framing of this whole
effort changes. Record the finding in `logbook/apifootball.md` before building
anything on top of it.

**Deliverable:** `scripts/apifootball/af_status_and_coverage.py` — read-only,
writes `data/reference/apifootball/coverage.json`, prints the season-depth table.

---

## Phase 1 — Reference dimensions

Cheap, static, fetch-once: `/countries`, `/leagues` (already cached in Phase 0),
`/venues` per country. Cached under `data/raw/apifootball/`.

---

## Phase 2 — The injuries spine

The reason we're here. For each (league, season) where Phase 0 said
`coverage.injuries` is true:

```
GET /injuries?league={id}&season={year}
```

~130 calls. Cache one file per league-season, exactly mirroring the Sportmonks
cache-first discipline: **a fetched response is written to disk before any
processing, and never re-fetched.**

Known gap from the catalog, worth stating up front: API-Football injuries carry
**no recovery date, no severity, no diagnosis** — where Sportmonks' `sideline`
object has `start_date`, `end_date`, `games_missed`, `completed`. So
API-Football gives *wider* injury coverage and Sportmonks gives *deeper* injury
records. Neither supersedes the other, and the comparison DB should make that
visible rather than papering over it.

---

## Phase 3 — Fixtures + season aggregates

- `/fixtures?league&season` — one call per league-season (paginate).
- `/standings?league&season` — one per league-season.
- `/teams?league&season` — one per league-season; feeds the team dimension.
- `/teams/statistics?league&season&team` — the ~2,600-call tail. Runs last,
  resumable, and can be interrupted without losing the spine.

---

## Phase 4 — Storage

Separate SQLite: **`data/apifootball.db`**, its own schema, its own ETL. It is a
rebuildable artifact like `app/app.db`; the raw cache is the durable record.

**No cross-vendor entity resolution in this pass.** Mapping a Sportmonks player
id to an API-Football player id is a genuinely hard, error-prone problem (names
collide, transliterations differ, no shared key), and guessing it wrong would
silently corrupt both datasets. Keep the two apart, compare at the aggregate
level first (counts per league-season), and only then decide whether a mapping
is worth attempting.

---

## Directory reshape

Sized against the actual code: **13 import lines** across 5 ingest modules and
1 test file. `scripts/` imports nothing from `ingest`. `app/etl.py` hardcodes
its own paths and does **not** import `ingest.paths`.

### Target layout

```
ingest/
  core/                    # vendor-neutral
    cache.py               # read_cache / write_cache (moved verbatim)
    http.py                # retry + response logging, no quota model
    months.py              # moved as-is
  sportmonks/
    __init__.py  client.py  paths.py  backfill.py  enrich.py
    resolve.py   squads.py  sync.py
  apifootball/
    __init__.py  client.py  paths.py
    leagues.py             # Phase 0/1
    injuries.py            # Phase 2
    fixtures.py            # Phase 3
scripts/
  sportmonks/              # the 24 sm_* probes, moved
  apifootball/
data/
  raw/sportmonks/          # UNCHANGED — app/etl.py points here
  raw/apifootball/
  reference/sportmonks/    # the 4 top-level sportmonks_*.json
  reference/apifootball/
logbook/
  sportmonks.md  apifootball.md
docs/
  sportmonks/  football-api/
```

### What is deliberately NOT shared

The **throttle model cannot be shared.** Sportmonks meters per-entity
rolling-hour buckets (`rate_limit.requested_entity` in every response);
API-Football meters a global daily quota plus a per-minute cap, reported in
response *headers*. Forcing one abstraction over both would produce a wrapper
that models neither correctly. `ingest/core/http.py` carries only what is
genuinely common — retry/backoff, response logging with credential redaction,
cache-first fetching — and each vendor client owns its own pacing.

### Execution order (each step independently verifiable)

1. **Create `ingest/core/`**, move `months.py` and the cache helpers. Rewrite
   imports. **Run the suite — must be green.**
2. **Create `ingest/sportmonks/`**, move the 7 modules, rewrite the 13 import
   lines. `data/raw/sportmonks/` does **not** move, so `app/etl.py` is
   untouched. **Run the suite — must be green.**
3. **Move `scripts/sm_*` → `scripts/sportmonks/`.** No imports to fix; these are
   standalone. Not test-covered — verify by running one or two by hand.
4. **Move the 4 `data/sportmonks_*.json` → `data/reference/sportmonks/`.**
   **This is the riskiest step**: 11 files reference these paths, 9 of them
   untested diagnostic scripts. Failures are loud (`FileNotFoundError` from
   `paths.load_leagues`), not silent — but do this last and separately so a
   breakage is unambiguous.
5. **Add `ingest/apifootball/` and `data/raw/apifootball/`.** Purely additive.

Steps 1–2 are covered by `tests/test_ingest.py`. Steps 3–4 are not; they need
manual spot-checks.

---

## Risks and open questions

- ~~**API-Football may add no history at all.**~~ **RESOLVED 2026-07-29:** it
  exposes 2020–2025 for 11 leagues. This is now the project's *only* route to
  pre-2024 domestic injury history, which raises the value of Phase 2 rather
  than lowering it.
- **The `coverage.injuries` flag was verified accurate for 2023/24** (our run 7
  counts matched the flag exactly for all 10 sampled leagues) but never
  count-verified for 2025 on a paid plan. Phase 2 verifies it for real.
- **Coverage moves.** San Marino was dark across the 2023–25 sample on
  2026-07-23 and shows 2025 coverage on 2026-07-29. Re-run Phase 0 periodically
  instead of trusting `data/reference/apifootball/coverage.json` indefinitely.
- **Coverage is a moving target.** ~32 leagues appearing to switch on at 2025
  suggests API-Football expanded injury coverage recently. Re-run Phase 0
  periodically rather than treating today's 43 as fixed.
- **`docs/football-api/overview.md` is empty.** The catalog describes endpoints
  but no measured vendor behaviour. `logbook/apifootball.md` should be created
  and appended to from the first call onward, on the same append-only discipline
  as `logbook/sportmonks.md`.
- **Unverified:** every rate-limit figure here comes from free-tier headers and
  API-Football's published plan table. Phase 0's `/status` is what makes them
  real.

---

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Plan tier | Pro, 7,500/day | Spine + aggregates (~3,200 calls) fits in a day |
| Scope | Spine + standings/team stats | Per-fixture enrichment is ~128k calls, 40x everything else |
| Reshape | Full, both vendors | Only 13 import lines; cheaper to do now than after a third vendor |
| Storage | Separate `apifootball.db` | Cross-vendor id mapping is error-prone; compare aggregates first |
