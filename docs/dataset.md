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

## Two things that trip everyone up

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

## What questions this lets us answer

- Which **positions** get injured most? Which **injury types** keep players out
  longest?
- Do **older players** get injured more often? Is there a **seasonal** pattern
  (injuries by month)?
- What's the injury **burden by league or country**?
- What does a **single player's** injury history look like over time?

## Coverage & honesty (the fine print)

- **Breadth:** 53 of the 55 UEFA top leagues resolve. (Liechtenstein has no
  domestic league; a couple sit outside the current plan.)
- **Depth:** the cache currently holds about the **last 3 years**; the
  historical backfill is extending this toward **2014**, as far back as
  Sportmonks actually has data.
- **Honest caveats:** a league is attributed from the fixture the record showed
  up in; season comes from that parent fixture; and a slice of incidentally
  referenced teams (cup opponents, lower divisions) never resolve to names. None
  of these are bugs — they're documented limits of what the source provides.

## A note on the current numbers

As a rough snapshot of the 3-year cache *before* the historical backfill: the
raw feed holds tens of thousands of fixture-level mentions that dedupe down to
roughly **17,000 distinct absences**, the majority of them genuine injuries.
These figures will grow as the backfill reaches further into the past — the
`data_quality` table always holds the live, measured counts after each rebuild.
