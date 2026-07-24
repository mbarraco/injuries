# Injury Data POC Web App — Design

**Date:** 2026-07-23
**Status:** Approved, ready for implementation planning
**Audience for the artifact:** a product owner evaluating whether this
dataset is real, trustworthy, and worth building on.

## Purpose

A FastAPI POC that showcases the Sportmonks injury dataset we assembled —
its **coverage**, its **data quality**, and the **analytical linkage**
possible once the raw API data is properly normalized. Sportmonks only;
API-Football comparison is deliberately out of scope (cleaner story, and
the Sportmonks-vs-API-Football history comparison rests on numbers still
unresolved pending the trial-restriction question).

## Why this needs a real ETL, not a view over raw JSON

The raw cache (1,979 fixture-month JSON files) is **not** injury records —
it is fixture-appearance rows. Measured:

| | |
|---|---|
| Raw pivot rows | 67,403 |
| Distinct absences (unique `sideline_id`) | 16,747 |
| Inflation factor | **4.0×** |
| Of those, actual injuries (`category == 'injury'`) | **10,047** |

Anyone counting raw rows overstates by 4×. Deduplication by `sideline_id`
is mandatory, and demonstrating that correction is itself a core part of
the data-quality story.

## Schema (`app/app.db`, new — built by ETL)

Deliberately a **new, separate database**. `coverage.db` stays untouched
as the investigation artifact; `app.db` is the product artifact. Clean
separation of provisional research state from curated data.

### Dimensions

```
league       (id, country, name, sportmonks_id)
season       (id, league_id, name, is_current)
team         (id, name, country, founded, short_code)
player       (id, name, position, detailed_position, nationality,
              date_of_birth, height_cm, weight_kg)
injury_type  (id, name)
```

### Fact — `injury`

One row per **distinct injury**. Suspensions and doubtful records are
excluded (see Category normalization).

```
injury (
  id                  PK   -- sideline_id (natural dedup key)
  player_id           FK -> player
  team_id             FK -> team          (98% filled)
  league_id           FK -> league         (attributed, see caveats)
  season_id           FK -> season         (from parent fixture, see caveats)
  type_id             FK -> injury_type
  start_date                               (100%)
  end_date                                 (93%; null = ongoing)
  games_missed                             (98%)
  completed
  fixture_appearances -- matches spanned; the dedup evidence
  duration_days       -- derived: end_date - start_date
  age_at_start        -- derived: start_date - player.date_of_birth
  is_ongoing          -- derived: end_date IS NULL
)
```

`age_at_start` and `duration_days` are materialized during ETL rather than
computed per query — they power the headline analytics and SQLite date
arithmetic in a hot path is not worth it.

### Provenance & quality

```
ingest_run   (id, run_at, source_file_count, notes)
data_quality (metric, value, detail)
```

`data_quality` holds **measured** values written by the ETL (resolution
rates, field fill rates, dedup ratio, exclusion counts). The app renders
these numbers from the table — it never hardcodes a quality claim.

### Category normalization

The vendor's `category` field has four values, including a genuine defect:

| raw value | count | disposition |
|---|---|---|
| `injury` | 10,047 | **kept** |
| `suspended` | 6,629 | excluded |
| `suspension` | 54 | excluded — *same concept, two spellings* |
| `doubtful` | 17 | excluded |

`suspended` vs `suspension` is a real vendor inconsistency worth surfacing
in the UI. Excluded counts are recorded in `data_quality` so the app can
state plainly: *"6,700 suspension records excluded — this is an injury
database, not an availability database."*

### Known caveats, encoded honestly

- **`league_id` is attributed**, not intrinsic: it comes from whose league
  fixture cache the record appeared in. A record surfacing in multiple
  competitions is resolved by first occurrence.
- **`season_id` comes from the parent fixture** — the vendor leaves
  `season_id` null on 100% of sideline records.
- **174 teams (18%) unresolvable** — out-of-plan gating, not an error.
- **36 player ids unresolvable** — genuine dead ids.
- **History depth is provisional** — the trial-vs-paid restriction question
  is unresolved; the app must not present history depth as settled fact.

## Application structure

```
app/
  etl.py          # raw JSON cache + coverage.db -> app.db
  db.py           # read-only connection + helpers
  queries.py      # one function per view; all SQL lives here
  main.py         # FastAPI routes (HTML + JSON)
  templates/      # Jinja2
  static/         # CSS
  app.db          # generated, gitignored
```

Server-rendered Jinja2 with Chart.js for visuals. No SPA, no build step —
for a POC where tables are the point, this is the shortest path to
something credible. Every page has a matching `/api/*` JSON endpoint, so
it demos as a real API rather than only a webpage.

Design intent: polished and presentable, not utilitarian. Clean
typography, restrained palette, real visual hierarchy, responsive tables.
This is going in front of a product owner.

## Pages

### `/` — Coverage & Data Quality
The scorecard, and deliberately the landing page. Hero stats (injuries,
leagues, players, teams, date range). The 4× dedup funnel shown visually
(67,403 raw → 16,747 distinct → 10,047 injuries). Resolution and fill
rates as measured bars. Coverage-by-league table with tiers across the
three year buckets. A **Known Gaps panel** stating limitations outright.

Leading with limitations is what makes the rest credible.

### `/analytics` — Linkage & Aggregation
The joins raw API data cannot do:
- injuries by **position** (player ⋈ injury)
- injuries by **age band** (derived from DOB × start_date)
- by **type** — count, avg duration, avg games missed
- by **nationality**, by **league**
- **seasonality** — injuries by month

Each view is a 2–4 table join; that is the showcase.

### `/injuries` — Explorable records
Filterable, sortable, paginated table (league, season, team, position,
type, date range, ongoing-only) plus a player drill-down showing that
player's full injury timeline.

## Out of scope

- API-Football data or provider comparison
- Live/incremental refresh (ETL is a batch rebuild from cache)
- Auth, multi-user, deployment
- Writing back to Sportmonks or any external service
