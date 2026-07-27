# Sportmonks Data Expansion & Repeatable Ingestion — Design

**Date:** 2026-07-26
**Status:** Approved, ready for implementation planning
**Supersedes (in part):** [2026-07-23-injury-data-poc-app-design.md](2026-07-23-injury-data-poc-app-design.md)
 — specifically its "Out of scope: Live/incremental refresh" decision, and
 its `injury`-only (category-filtered) schema. API-Football staying out of
 scope is **reaffirmed**, not changed.

## Purpose

Expand the Sportmonks raw data cache and turn the one-off sweep/resolve
scripts into a small, repeatable ingestion pipeline, while the 14-day Pro
trial is still active (~10 days remaining at design time). Three concrete
gaps drive this:

1. **History is capped at 36 months** by `sm_sweep55.py`, even though the
   real archive goes back to at least October 2014 (logbook-verified).
2. **Entity resolution is incomplete**: 174/975 referenced teams and
   36/10,770 referenced players were never fetched.
3. **`app/etl.py` silently drops non-`injury` categories** — 12,667
   suspension rows never reach `app.db` today.

   > **Correction (2026-07-27):** this point originally also claimed 19,533
   > `unknown`-category rows were being dropped. That was a miscount, and no
   > such records exist. `unknown` was tallied per *pivot row*, but the feed
   > repeats an absence once per missed fixture and often omits the nested
   > `sideline` object on the repeats — so the same absence shows as
   > `unknown` on some rows and with its real category on others. Counted per
   > distinct `sideline_id` (what the ETL actually loads), **zero** absences
   > are uncategorised. The suspension half of this gap was real, so the
   > category-preserving `absence` schema below still stands.

Because Sportmonks quota resets hourly and out-of-plan access degrades
silently (200 + empty `data`, not 403 — see the logbook), the pipeline
needs proper per-entity throttling awareness, not just a bigger one-shot
script.

## Current state (measured, 2026-07-26)

| | |
|---|---|
| Fixture cache | 1,979 files = 53 leagues × 36 months (1 league missing 1/36 months) |
| Stale cache files under old wrong league ids | 2 (Georgia `316`, Gibraltar `1526` — pre-dates a league-id bugfix, never cleaned up) |
| Distinct absences (`sideline_id`) | 16,747 |
| Raw pivot rows by category | injury 54,663 · suspended 12,329 · suspension 338 · doubtful 73 · unknown 19,533 |
| Players cached / referenced | 10,734 / 10,770 |
| Teams cached / referenced | 801 / 975 |

The `unknown 19,533` above is a **pivot-row** count, not an absence count —
see the correction under gap 3. Per distinct `sideline_id` there are no
uncategorised absences.

### Superseded by the 2026-07-27 expansion

A subscription upgrade made 9 further leagues visible, including the UEFA
club competitions the original 53-league domestic list never covered
(Champions League, Europa League, Conference League, Super Cup). Backfilled
and enriched the same day; `scripts/sm_find_missing_leagues.py` now diffs the
API's `/leagues` against the reference file so a stale list can't hide
in-plan competitions again.

| | before | after |
|---|---|---|
| Leagues backfilled | 53 | 62 |
| Fixture-month files | 8,003 | 9,362 |
| Non-empty months (all rich) | 1,116 | 1,454 |
| Distinct absences | 16,770 | 25,890 |
| — of which injuries | — | 18,380 |
| Players cached | 10,737 | 13,130 |
| Teams cached / referenced | 801 / 977 | 867 / 1,109 |

Orphan teams rose to 244: UCL/UEL qualifying rounds reference clubs outside
the 62 in-plan leagues, and those fetches return the usual silent 200 + empty
`data`. Expected, not a defect.

## Architecture

New `ingest/` package, sibling to `app/` and `scripts/`:

```
ingest/
  sportmonks_client.py   # shared throttle-aware HTTP layer + raw-JSON cache
  paths.py               # cache/reference filesystem layout + league loader
  months.py              # pure calendar-month window arithmetic
  resolve.py             # entity id -> name resolution into coverage.db
  backfill.py            # wide date-range fetch + watermark (replaces sm_sweep55.py
                          # and the fixture-resolution half of sm_resolve_entities.py)
  sync.py                # incremental fetch from the stored watermark
```

(Implementation note: the original 3-file sketch grew to 6 small,
single-purpose modules — `paths`/`months`/`resolve` were split out rather
than crammed into `backfill.py` — for testability and clear boundaries.)

### `sportmonks_client.py`

Factors out the logic currently duplicated near-verbatim across
`sm_sweep55.py` and `sm_resolve_entities.py`:

- 429/`Retry-After` handling (already proven against a real rate-limit hit
  — kept as-is)
- JSONL response logging (same format as today)
- Generic pagination follower (`per_page=100`, follow `has_more`)
- Raw-cache read/write helpers, keyed by exactly what was queried (same
  "one file per query" pattern as today — a cache hit skips the network
  call entirely)
- **Per-entity quota tracking**: every response's `rate_limit` block
  (`remaining`, `requested_entity`, `resets_in_seconds`) is recorded per
  entity (Fixture, Player, Team, League, Season, Type — each an
  independent rolling-hour bucket per the logbook). Callers can check
  remaining quota for an entity before firing a large batch, on top of —
  not instead of — the reactive 429 handler.

### `backfill.py`

- Arbitrary date range via CLI (`--since 2014-01`, default extends back as
  far as data exists rather than a hardcoded 36 months)
- Same per-league-per-month raw cache file layout as today
- Resumable: already-cached months/entities are skipped, so re-running
  during the remaining trial window never re-spends quota
- After each fixture pass, resolves any newly-referenced player/team ids
  (folding in `sm_resolve_entities.py`'s entity-resolution logic)
- Writes a **watermark**: per league, the latest month with fetched
  fixture data. This is what `sync.py` reads.

### `sync.py`

- Reads the watermark, fetches only fixture-months after it per league
  (normally just the current/trailing month)
- Resolves newly-referenced entities
- Advances the watermark on success
- Makes future re-runs (whenever — post-trial, on a paid plan, etc.) cheap
  and correct. Scheduling it (cron or similar) is **out of scope** for
  this design — this only makes re-running safe and correct, not
  automatic.

### Left alone

`scripts/sm_check_*.py`, `sm_explore.py`, `sm_deep.py`, `sm_probe_squads.py`
and similar stay in `scripts/` — they're investigation/diagnostic tools,
not part of the ingestion pipeline. `sm_sweep55.py` and
`sm_resolve_entities.py` are retired once `ingest/backfill.py` covers their
functionality.

## Data flow & schema change

1. `ingest/backfill.py` (run repeatedly over the remaining trial window) →
   widens `data/raw/sportmonks/fixtures/*.json` back toward 2014 where
   data exists, and fills the player/team resolution gaps.
2. `app/etl.py build` → rebuilds `app/app.db` from the entire raw cache
   (unchanged rebuild-from-scratch approach — still fast, still
   idempotent).
3. `ingest/sync.py` → later, tops up the raw cache incrementally; the next
   `etl.py build` picks up whatever's new.

### Schema: `injury` → `absence`

The prior design's `injury` table (category-filtered to `injury` only) is
replaced with an `absence` table holding **every** `sidelined` record,
with the raw Sportmonks `category` string kept as a column instead of
being used as an inclusion filter:

```
absence (
  id                  PK   -- sideline_id
  player_id           FK -> player
  team_id             FK -> team
  league_id           FK -> league
  season_id           FK -> season
  type_id             FK -> injury_type
  category                              -- injury / suspended / suspension /
                                         -- doubtful / unknown / ...
  start_date
  end_date                              -- null = ongoing
  games_missed
  completed
  fixture_appearances
  duration_days
  age_at_start
  is_ongoing
)
```

`app/queries.py` and templates that specifically mean "injuries" (e.g. the
injuries list page) filter on `category = 'injury'` at the query layer —
existing pages keep showing what they show today. The difference is
nothing is silently dropped during ingest, and suspensions/unknowns become
queryable.

`unknown`-category rows are included as-is (`category = 'unknown'`), not
gated on investigation — but `data_quality` gets a metric noting the count
and a spot-check note on likely cause, since that's cheap and may surface
a real vendor data-quality issue worth flagging later.

**As built (2026-07-27):** the handling is unchanged, but the case never
arises — the measured count is zero (see the correction under gap 3). The
`data_quality` per-category metrics are emitted regardless, so a future
genuinely-uncategorised row would still show up.

## Throttling

- Quota tracked **per entity** (Fixture, Player, Team, League, Season,
  Type), matching Sportmonks' independent rolling-hour buckets (Pro:
  3000/hr each, per the logbook).
- Concurrency stays capped per entity (default 3, configurable via CLI) —
  since buckets are independent, a fixtures backfill and a
  player/team-resolution pass may run concurrently with each other without
  competing for the same bucket.
- Proactive: client surfaces remaining quota per entity so a runner can
  pace or pause before a large batch.
- Reactive: 429 → sleep for `Retry-After` (unchanged, already proven).

## Error handling

- 429 → respect `Retry-After` (existing behavior).
- Other non-200 (5xx, network) → bounded retry with backoff, then
  log-and-skip so one bad month/entity doesn't abort the whole run.
- Out-of-plan ids (200 + empty `data`) are expected, not an error — no
  special handling beyond what already exists (see logbook: "out-of-plan
  access is silent").

## Testing

Mostly a network-fetching pipeline against a real, quota-limited API — no
live-API tests (would burn real quota). Realistic coverage:

- Pagination-follower logic against a mocked multi-page response sequence
- Watermark read/advance logic
- Cache-hit vs. cache-miss branching
- `etl.py` category-preservation: a small fixture file with mixed
  categories → assert every category lands in `absence` with the correct
  `category` value

## Cleanup included in this work

- Delete the 2 stale fixture cache files under old wrong league ids
  (`316_*.json`, `1526_*.json`)
- Backfill the 1 missing Gibraltar month

## Out of scope

- API-Football data or provider comparison (reaffirmed from the prior
  design)
- Scheduling `sync.py` to run automatically (cron, etc.) — this design
  only makes re-running safe and correct, not automatic
- Auth, multi-user, deployment changes to the web app
- Resolving the open "does the trial restrict historical depth vs. a paid
  plan" question — `backfill.py` will surface real evidence either way as
  it runs, but answering it isn't a goal of this work
