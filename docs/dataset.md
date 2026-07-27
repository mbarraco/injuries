# What dataset are we building?

A plain-language tour of the data this project collects and stores. No SQL
knowledge needed. (For the exact table columns, see [app/schema.sql](../app/schema.sql);
for the gory API details, see [logbook/sportmonks.md](../logbook/sportmonks.md).)

## In one sentence

We're building a database of **player absences — mostly injuries — across the
top-flight football league of every UEFA country**, with enough context to ask
*who* got hurt, *how badly*, *how often*, and *what it depends on*.

## What one record actually is

Every row in the main table is **one spell a player spent sidelined**. Read in
human terms, a record says something like:

> *A. Player, a **centre back** at FC Test, had a **hamstring** injury. He was
> out from **1 Feb 2024** to **1 Apr 2024** and missed **8 matches**.*

That's the unit. Everything else in the dataset exists to describe, group, or
count these spells.

## Where the data comes from

All of it comes from the **Sportmonks** football API. There's a catch that
shapes everything: Sportmonks has no "list of injuries" endpoint. Injuries only
appear as `sidelined` entries riding along on **fixtures** (matches). So we walk
through fixtures month-by-month for each league and lift the sidelined data out.
That's why the raw files are organised by league and month.

## The three layers of storage

```
   Sportmonks API
        │  (fetch once, cache forever)
        ▼
┌─────────────────────────┐
│ 1. RAW CACHE            │   data/raw/sportmonks/
│    exact API responses  │   • fixtures/{league}_{month}.json
│    saved to disk        │   • players/{id}.json, teams/{id}.json
└───────────┬─────────────┘   the durable archive — never re-fetched
            │
            │  (the ETL reads raw + reference…)
            ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│ 2. REFERENCE LOOKUPS    │   │ 3. CURATED DATABASE     │
│    id → human name      │──▶│    clean & queryable    │
│    coverage.db          │   │    app/app.db           │
└─────────────────────────┘   └───────────┬─────────────┘
                                           │
                                           ▼
                                    the web app reads this
```

1. **Raw cache** (`data/raw/sportmonks/`) — the untouched API responses, one
   file per (league, month) for fixtures and one per player/team. This is the
   **source of truth** and the whole reason the project survives the trial: once
   a response is on disk, we never pay to fetch it again.
2. **Reference lookups** (`coverage.db`) — small tables that turn the numeric
   ids in the raw data into names: which player, team, country, and injury type
   each id refers to.
3. **Curated database** (`app/app.db`) — the tidy result the app actually
   queries, rebuilt from layers 1 and 2 by the ETL. Throw it away and rebuild it
   any time; the raw cache is what's precious.

## What's inside the curated database

**The "nouns" (dimension tables)** — the things an absence refers to:

| Table | Describes | Examples of what it holds |
|---|---|---|
| `player` | the person | name, position, nationality, date of birth, height, weight |
| `team` | the club | name, country, founded year |
| `league` | the competition | country, league name |
| `season` | the season | e.g. 2024/2025 |
| `injury_type` | the kind of problem | "Hamstring", "Knock", "Muscular problems", "Suspended" |

**The heart of it (`absence` table)** — one row per distinct sidelining, joining
those nouns together with the facts:

- **who / where** — player, team, league, season
- **category** — `injury`, `suspended`, `suspension`, `doubtful`, or `unknown`
- **type** — the specific injury type
- **start_date / end_date** — when it began and ended (*no end date = still
  ongoing*)
- **games_missed** — matches missed during the spell
- **duration_days**, **age_at_start**, **is_ongoing** — convenience fields we
  compute once so the app doesn't have to

**Two "about the data" tables** — `data_quality` (measured stats: how many
records, how complete the fields are, etc.) and `league_coverage` (how much data
each league has, per period).

## Three things that trip everyone up

**1. The raw feed double-counts.** Because injuries ride on fixtures, *one*
injury is repeated once for *every match the player missed*. A 7-game injury
appears 7 times in the raw data. We **deduplicate** down to one row per real
spell — so our counts are actual injuries, not match-appearances. (We keep the
original repeat-count in `fixture_appearances` as evidence of the correction.)

**2. It's not only injuries.** The same feed mixes in suspensions and some
uncategorised entries. We now **keep all of them** in the `absence` table
(nothing is silently thrown away), but the app's views focus on
`category = 'injury'`. So the database is a little broader than "injuries" if you
ever want to look at suspensions too.

**3. Injury coverage improves over time — so DON'T compare years.** This is the
big one. Sportmonks recorded almost no absences in the early years and has got
steadily more thorough since. Sidelined records per fixture, from the
`coverage_<year>` rows in `data_quality`:

| 2000–06 | 2009 | 2012 | 2014 | 2017 | 2020 | 2022 | 2024 | 2026 |
|---|---|---|---|---|---|---|---|---|
| 0.00 | 0.10 | 0.41 | 0.76 | 1.62 | 3.23 | 3.96 | 3.21 | 3.93 |

**There are literally zero injury records before 2006.** A chart of "injuries per
season since 2000" would show a dramatic rise that is *entirely* the provider
getting better at recording them — nothing to do with football.

Two things to read carefully here:

- **The ramp is steep up to ~2020, then roughly flat (~3–4).** So recent seasons
  are broadly comparable with each other; anything reaching back past 2020 is
  not.
- **The series changes composition in 2024.** Before then it's UEFA cups only
  (domestic seasons don't exist in our data); from 2024 it's cups *plus* 58
  domestic leagues, which run a lower density. So the 2023 → 2024 step mixes a
  coverage change with a competition-mix change and shouldn't be read as either
  one alone.

For a clean like-for-like trend, filter to a single competition — the cups are
the only ones with real history, and cups-only density keeps climbing (to ~6.9
by 2025) rather than flattening.

## What questions this lets us answer

- Which **positions** get injured most? Which **injury types** keep players out
  longest?
- Do **older players** get injured more often? Is there a **seasonal** pattern
  (injuries by month)?
- What's the injury **burden by league or country**?
- What does a **single player's** injury history look like over time?

## Coverage & honesty (the fine print)

- **Breadth:** 62 competitions — 58 domestic UEFA leagues plus the **Champions
  League, Europa League, Conference League and Super Cup**. (Liechtenstein has
  no domestic league of its own.)
- **Depth is very uneven, and this is a hard limit of the subscription:**
  - **Domestic leagues: 3 seasons only** (2024/25 onward). The plan simply
    doesn't sell older seasons, and fixtures can only be fetched for seasons
    it includes — so there is *no* domestic data before 2024 and no way to
    fetch any. England's Premier League has zero fixtures for 2014–2023.
  - **UEFA cups: back to 2000** (Conference League to 2021, when it was
    founded). This is where all the long history lives — though see gotcha 3:
    the early years hold fixtures but almost no injury records.
- **Honest caveats:** a league is attributed from the fixture the record showed
  up in; season comes from that parent fixture; and a slice of incidentally
  referenced teams (cup opponents, lower divisions) never resolve to names. None
  of these are bugs — they're documented limits of what the source provides.

## A note on the current numbers

Measured after the 2026-07-27 rebuild, once the backfill had reached as far as
the subscription allows in both directions:

| | |
|---|---|
| Distinct absences | **26,408** |
| — of which injuries | 18,898 |
| Player-seasons (playing time) | 44,213 |
| Transfers | 77,152 |
| Players / teams | 13,315 / 867 |

The raw feed's ~117,000 fixture-level mentions dedupe down to those 26,408 real
spells. The `data_quality` table always holds the live, measured counts after
each rebuild, so treat that as the source of truth rather than this snapshot.

There is no more data to fetch on this plan: domestic seasons are capped at 3,
cup history is exhausted back to 2000, and absences can only be reconstructed
from fixtures (there is no player-level injury endpoint). Further work is
analysis, not collection.
