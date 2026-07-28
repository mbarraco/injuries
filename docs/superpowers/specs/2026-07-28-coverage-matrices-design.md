# Coverage Matrices — Design

**Date:** 2026-07-28
**Status:** Approved, ready for implementation planning
**Builds on:** [2026-07-27-injury-app-redesign-design.md](2026-07-27-injury-app-redesign-design.md)

## Purpose

Cross-tabulations ("double entry" tables) showing **how much data the dataset
holds** across season × league, season × club and season × player. Aimed at
stakeholders who need to understand what is and isn't in here.

The framing is deliberate. A season-by-season grid invites exactly the
comparison the logbook records as invalid: sidelined coverage ramps from 0.00
records per fixture before 2006 to roughly 4 today, so a grid read as "injuries
over time" measures the vendor's backfill rather than football. Read instead as
**"what do we hold, and where are the gaps"**, that same variation is the
finding — and needs no caveat, because the tables no longer claim to be about
injuries at all.

## Prerequisite: the league and season dimensions are incomplete

**This is a live bug, worth fixing regardless of the matrices.**

| | measured 2026-07-28 |
|---|---|
| Rows in `league` | 53 — the four UEFA cups are absent |
| Rows in `season` | 159 (53 domestic leagues × 3 seasons) |
| Absences whose `league_id` is not in `league` | **11,118 of 26,408 (42%)** |
| Absences whose `season_id` is not in `season` | the same 11,118 |

One root cause: both dimensions are derived from `coverage.db.sportmonks_season`,
which only ever covered the 53 domestic leagues. `ingest/resolve.py` populates it
from the league list it sweeps, so the nine competitions added on 2026-07-27 —
Champions League, Europa League, Conference League, Super Cup and five play-off
competitions — never reached it.

Consequences already visible in the app: the dashboard reports **53
competitions when the dataset holds 62**, and every cup absence renders with a
blank competition because the name does not resolve.

**The data is already on disk.** `data/raw/sportmonks/seasons/{league_id}.json`
holds a league object with its full `seasons` array for all 62 leagues —
Champions League has 27 seasons there, back to 2000. `scripts/sm_check_season_depth.py`
cached them. No API calls are needed.

### Fix

`app/etl.py` gains `collect_leagues_and_seasons(reference, seasons_dir, countries_file)`,
mirroring the existing `collect_types()`:

- Read every `seasons/*.json`; each file yields one league row and many season rows.
- Resolve country names through the cached `countries.json` (238 entries keyed
  `id` → `name`, verified) — the season files carry `country_id`, not a name.
  The UEFA cups resolve to "Europe" through the same path.
- Fall back to `coverage.db` for anything the cache lacks, so a missing cache
  degrades to today's behaviour rather than losing rows.

Expected after the fix: leagues 53 → 62, seasons 159 → ~240, and the 11,118
orphaned absences gain both a competition and a season.

## The season axis

Columns are **season labels, not season ids**. There are 159 season rows but
only 6 distinct labels among domestic leagues:

```
2024   2024/2025   2025   2025/2026   2026   2026/2027
```

Season ids are per-league, so using them would produce 159 near-empty columns
where each club appears in only its own league's seasons. Labels collapse that
into a dense, readable axis. The cup seasons restored by the prerequisite add
their own labels, extending the axis backwards.

Calendar-year leagues (Nordic, Baltic) and autumn-spring leagues keep
**separate columns**. `2025` and `2025/2026` are different calendars; merging
them would invent a comparison the data does not support.

## Routes

Named `/admin/matrix/...` rather than `/admin/coverage/...`: `/coverage` already
exists and means the quality-and-caveats page, so reusing the word would blur
two different things.

| Route | Grid |
|---|---|
| `/admin` | Index — what each matrix shows, and the coverage framing stated once |
| `/admin/matrix/<measure>` | season × league |
| `/admin/matrix/<measure>/league/<id>` | season × club, that league's clubs only |
| `/admin/matrix/<measure>/team/<id>` | season × player, that club's players only |

`<measure>` is one of `absences`, `transfers`, `minutes`, `fixtures`.

Same authentication as the rest of the app — `/admin` is a URL grouping, not a
new access tier. There are no per-user accounts today, so a genuinely
restricted area would need an auth story that does not exist yet.

### Why drill-down rather than one large grid

867 clubs × 6 columns is technically renderable but unreadable. The top level is
season × league (62 rows), and clicking a league gives season × club for its
clubs alone (~20 rows). Every grid stays small enough to scan without scrolling,
and the path matches how football people navigate: competition, then club, then
player.

## Measures

| Measure | Source | Note |
|---|---|---|
| `absences` | `absence` | Injuries and suspensions |
| `transfers` | `transfer` | **Bucketed by date** — see below |
| `minutes` | `player_season` | Players with recorded playing time; the denominator behind injury rates |
| `fixtures` | new `fixture_coverage` table | Not otherwise present in `app.db` |

**Transfers carry no `season_id`** — only a date. They are bucketed into season
windows by date, which is an approximation, not a lookup: league calendars
differ, so a July move sits ambiguously between two seasons. The UI states this
where transfer grids appear rather than presenting the bucketing as exact.

**Fixtures are not in `app.db` at all** — they live only in the raw cache's
9,866 files. A new table is populated during the ETL's existing scan:

```sql
CREATE TABLE fixture_coverage (
    league_id        INTEGER REFERENCES league(id),
    season_id        INTEGER REFERENCES season(id),
    fixtures         INTEGER,
    non_empty_months INTEGER,
    PRIMARY KEY (league_id, season_id)
);
```

Keyed on **`season_id`, not a season label**: cached fixtures carry
`fixture.season_id` (verified), but the label lives in the `season` dimension,
which `build()` loads *after* the cache scan. Storing ids keeps this a
single-pass aggregation and lets the label be joined at query time — the same
way every other table resolves its dimensions. `collect_absences()` already
walks every cached file, so the counts come almost free rather than needing a
second pass.

Some cached fixtures reference seasons outside the dimension even after the
prerequisite fix. Those rows are retained with an unresolvable `season_id`
rather than dropped, and surface in the grid's "unattributed" column — losing
them would understate coverage, which is the one thing these tables must not do.

## Query layer

A new module `app/matrix.py`, kept out of `queries.py` — that file is already
large, and twelve more statements would push it past the point where it is
comfortable to work in.

Each measure declares its own complete SQL per row dimension:

```python
MEASURES = {
    "absences": Measure(label="Absences",
                        by_league=..., by_club=..., by_player=...),
    ...
}
```

Twelve literal statements rather than one assembled query. This is deliberately
not a generic cross-tab engine: a generic version would interpolate identifiers
against a whitelist and return an untyped shape, which is harder to read and
test for four measures and three dimensions. YAGNI — write the twelve.

Every function returns the same structure, so a single template macro renders
all of them:

```python
{"seasons": ["2024/2025", ...],           # column headers, ordered
 "rows": [{"id": 8, "label": "Premier League",
           "cells": {"2024/2025": 412, ...},
           "total": 798}],
 "column_totals": {...}, "grand_total": ...}
```

Pivoting happens in Python from a `GROUP BY row, season` result, not in SQL.
The season axis is small and known, but it grows as cup seasons are restored,
and a SQL pivot would hardcode the columns.

## Rendering

One `matrix` macro in `macros.html`, shared by every grid: numbers with
background intensity scaled to the largest value in the grid, row and column
totals, and clickable row labels drilling into the next dimension.

**Empty cells render blank; a real zero renders `0`.** For a coverage view
these are different claims — "we hold nothing for this club in this season"
versus "we hold data and it recorded no events" — and collapsing them would
destroy the distinction the tables exist to show.

**Every grid ends with an "unattributed" column** counting records whose season
cannot be resolved, for any measure. The prerequisite fix removes most of
today's 11,118, but records referencing seasons outside the dimension will
remain, and a coverage table that quietly omits them would overstate how
complete the dataset is. If the column is empty it is hidden, so it appears
only when it has something to report.

Wide grids scroll horizontally inside `.table-wrap`, as elsewhere, and the row
label column stays readable.

## Testing

The existing fixtures already span two seasons (77 current, 78 not) and two
clubs, so cross-tab shape is testable without new scaffolding.

- Values land in the correct cells — a row's counts match a direct query.
- A league with no data still appears, as a row of blanks rather than absent.
- Empty and zero render differently.
- The prerequisite fix genuinely resolves previously-orphaned absences: assert
  the count of absences with an unresolvable league drops to zero.
- Transfer bucketing puts a known date in the expected season column.
- `fixture_coverage` is populated by a build and matches a direct cache count.

## Out of scope

- Per-user accounts or a real access tier behind `/admin`.
- Injury *rates* in matrices. Rates are season-scoped with a minutes floor and
  belong on entity pages; a rate grid across seasons would reintroduce exactly
  the invalid comparison this design avoids.
- Charting the matrices. They are tables; a heatmap is the visualisation.
- Export (CSV/Excel). Worth considering once the grids exist and are trusted.

## Risks

- **The grids get read as football findings anyway.** Mitigated by framing,
  page copy, and by keeping rates out — but a stakeholder can still misread a
  table. The `/admin` index states the intent once, prominently.
- **The prerequisite changes existing numbers.** Competitions go 53 → 62 and
  previously blank league cells populate. That is a correction, not a
  regression, but it will look like a change in the data and should be called
  out when it ships.
