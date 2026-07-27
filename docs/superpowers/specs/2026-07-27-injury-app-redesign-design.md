# Injury App — UX/UI Redesign & Full Entity Linking

**Date:** 2026-07-27
**Status:** Approved, ready for implementation planning
**Builds on:** [2026-07-26-sportmonks-data-expansion-design.md](2026-07-26-sportmonks-data-expansion-design.md)
 — that design filled the database; this one exposes it.

## Purpose

Turn the injury POC into the foundation of a real product. Two goals, from the
request:

1. **UX/UI** — the app has no search, no cross-links, dated styling, and shows
   numbers without context.
2. **Data presentation** — everything should be linked and expandable: detail →
   lists → related information.

## Current state (measured, 2026-07-27)

| | |
|---|---|
| Pages | 4 (`/`, `/analytics`, `/injuries`, `/player/{id}`) |
| Links in the entire app | **1** (player name → `/player/{id}`) |
| `queries.py` | 150 lines, single module |
| Templates | 5 files, each written as one dense line |
| `style.css` | a single minified line |
| Tests | 32 passing (`test_api.py` = 42 lines) |

**Tables in `app.db` the UI never touches:**

| Table | Rows | Consequence |
|---|---|---|
| `player_season` | 44,213 | Minutes played are invisible — the denominator that makes injury *rate* computable, and the whole reason it was captured |
| `transfer` | 77,152 | Unused |
| `absence` (non-injury) | 7,510 | App reads only the `injury` view, so suspensions are hidden |
| `coverage_<year>` metrics | 27 | Buried as raw rows in a generic metrics table |

Teams, leagues, seasons and injury types have **no pages at all** — they appear
only as dead text in table cells.

### Stale content to fix

`templates/coverage.html` still claims *"History depth is provisional. Sparse
older coverage may reflect trial-account restrictions; it is not presented as a
settled limitation."* This was settled on 2026-07-27: domestic leagues are
capped at 3 seasons by the plan, cups reach back to 2000 (see the logbook). Its
"Year 1 / Year 2 / Year 3" coverage table also encodes the old 3-year model and
does not fit 62 competitions.

## Approach

**Server-rendered FastAPI + Jinja, progressively enhanced with htmx** (~14kb,
vendored alongside the existing `chart.min.js`). Routes return a full page or an
HTML fragment; search, filtering and paging swap fragments without a reload.

Chosen over a JSON-API-plus-JavaScript client because it keeps **exactly one
rendering path**. Rendering rows in Jinja for the initial load and again in JS
for updates guarantees the two drift apart. Rejected an SPA outright: it buys
interactivity this app doesn't need, in exchange for a build toolchain and a
rewrite of working view code.

## Routes & navigation graph

| Route | Purpose |
|---|---|
| `/` | Dashboard — headline numbers, coverage caveat, entry points |
| `/absences` | Main list, with category filter (injuries / suspensions / all) |
| `/players` `/teams` `/leagues` `/seasons` `/types` | Searchable index pages |
| `/player/{id}` `/team/{id}` `/league/{id}` `/season/{id}` `/type/{id}` | Detail pages |
| `/analytics` | Kept; every aggregate row becomes a link |
| `/coverage` | Quality & coverage, moved off `/` |
| `/search?q=` | Global search (htmx fragment) |

**Redirects:** `/injuries` → `/absences?category=injury`, preserving existing
links and bookmarks.

### Linking rules

Each detail page carries its own data **and** links to every neighbour:

- **Absence row** → player · team · league · type · season (5 links; today 1)
- **Player** → current team, all teams, leagues, types suffered, transfer
  history (clubs linked), per-season minutes (seasons linked)
- **Team** → squad, league, absences, transfers in/out, injury burden
- **League** → teams, seasons, absences, type profile, coverage depth
- **Type** → players affected, absences, position breakdown, severity
- **Season** → leagues active, absences, players with minutes

Breadcrumbs on every detail page (`Home › Premier League › Arsenal › Saka`) and
a persistent global search in the header.

### Two renames

- **`/injuries` → `/absences`.** The table is `absence` and now surfaces
  suspensions; keeping the name "injuries" would be false once the category
  filter exists.
- **Coverage moves off `/`.** Good POC landing page, poor product homepage.

## Data & queries

### Injury rate — and its guard

Rate = injuries ÷ (minutes ÷ 1000), joining `absence` to `player_season`.

**Small denominators produce nonsense.** A player with 90 minutes and one injury
scores 11.1 per 1,000 minutes — twenty times "worse" than an ever-present
starter, purely as an artefact. Therefore:

- **Minimum 450 minutes (≈5 matches)** for a player to enter any rate ranking, as
  a named constant rather than a magic number.
- **Raw minutes shown beside every rate**, so the basis is always visible.
- Players below the threshold are **greyed out or footnoted, never silently
  dropped** — a hidden exclusion is how a reader draws a wrong conclusion.
- **Rates are scoped to a single season** by default. The `coverage_<year>` ramp
  (0.00 pre-2006 → ~4 today) means cross-year rate comparison measures vendor
  coverage, not injury risk.

### Category filter

Queries move from the `injury` view to the `absence` table with a `category`
parameter (`injury` / `suspended` / all). The `injury` view stays for backward
compatibility.

### Global search

13,315 players, 867 teams, 62 leagues — small enough that `LIKE 'q%' COLLATE
NOCASE`, unioned across entity types and capped at ~8 results each, is fast. No
FTS5, no new dependency.

Constraint: `db.connect()` opens the database **read-only** (`mode=ro`), so any
search index would have to be built by the ETL. Avoided by relying on indexed
prefix matching instead.

### Missing indexes

The new pages table-scan without these; none currently exist:

```sql
CREATE INDEX idx_absence_team        ON absence(team_id);
CREATE INDEX idx_player_season_season ON player_season(season_id);
CREATE INDEX idx_player_season_team   ON player_season(team_id);
CREATE INDEX idx_transfer_from        ON transfer(from_team_id);
CREATE INDEX idx_transfer_to          ON transfer(to_team_id);
```

### Module split

`queries.py` (150 lines) would reach ~500 with five detail pages, rate and
search. Split into a package:

```
queries/
  overview.py    dashboard + quality metrics
  absences.py    list, filters, pagination
  entities.py    player / team / league / season / type detail
  analytics.py   aggregations
  search.py      global search
```

## Templates & styling

```
templates/
  base.html      nav, header, search, breadcrumbs
  macros.html    table, pill, stat-tile, entity-link, empty-state
  pages/         one file per page
  partials/      htmx fragments
```

The `entity_link()` macro is what makes linking **consistent**: every player or
team reference renders identically, with one shared fallback for unresolved
names — which matters given 244 orphan teams and 21 orphan players that will
never resolve.

`style.css` becomes a real stylesheet: design tokens (color, spacing, type
scale), light/dark via `prefers-color-scheme`, and tables that scroll
horizontally on mobile instead of breaking layout.

### Explanation layer

Numbers get context where they appear: coverage warnings inline on any
year-spanning view, "based on N minutes" beside every rate, and a plain-language
note per page on what it can and cannot tell you. The `coverage_<year>` ramp
becomes a chart on `/coverage` and `/analytics`.

## API surface

The existing `/api/*` endpoints are a public-ish contract (documented at
`/docs`), so they change conservatively:

- **`/api/injuries` keeps working unchanged**, defaulting to `category=injury`.
  It gains an optional `category` parameter rather than being renamed, so no
  existing caller breaks.
- **`/api/absences`** is added as the name matching the new model; both hit the
  same query layer.
- Each new entity gets a read endpoint (`/api/team/{id}`, `/api/league/{id}`,
  `/api/season/{id}`, `/api/type/{id}`) mirroring its page, since the page
  queries already exist and exposing them is nearly free.
- **`/api/search`** backs both the header search and external callers.

htmx fragments are **not** part of the API: they live under the page routes and
return HTML, not JSON, so the two surfaces stay clearly separated.

## Auth

Split by consumer:

- **Humans** — login form with a signed session cookie via Starlette's built-in
  `SessionMiddleware` (no new dependency). Provides a real logout, which HTTP
  Basic cannot.
- **`/api/*`** — keeps HTTP Basic so `curl` and scripts stay simple.
- Credentials move to **environment variables** (`.env` is already gitignored),
  compared with `secrets.compare_digest` instead of `!=` to close the timing
  leak.

**The current password is in git history.** Moving it to env vars protects
future commits but does not remove it from the past — that credential must be
treated as burned and replaced, not reused.

## Infra

- **`app/app.db` → git-lfs.** Keeps clone-and-run working while stopping history
  growth. **Caveat: `git lfs track` only affects future commits.** The 14
  existing blobs remain in history unless rewritten with `git-filter-repo`,
  which rewrites SHAs and breaks existing clones — proposed as a **separate,
  optional** decision, not part of this work.
- Delete the empty `app/requirements.txt` (0 bytes) and fix `app/README.md`,
  which currently instructs `uv pip install -r app/requirements.txt` — a command
  that installs nothing since `pyproject.toml` superseded it.
- Add `.DS_Store` to `.gitignore` (currently committed).

## Testing

The 32 existing tests keep passing. Additions:

- `test_api.py` credentials move from hardcoded `fernando:1nd3p3nd13nt3` to an
  env-var fixture.
- Each entity page renders and contains its expected outbound links.
- The 450-minute threshold genuinely excludes low-minute players from rate
  rankings.
- Category filtering returns the right rows for injury / suspended / all.
- Search matches by prefix across entity types.

## Out of scope

- Rewriting git history to purge existing `app.db` blobs (separate decision).
- Per-user accounts, roles, registration — one shared credential remains.
- Any change to the ingest pipeline or ETL beyond the new indexes.
- New data capture: the dataset is at its plan ceiling (see the logbook).

## Risks

- **Rate metric misread.** The strongest mitigation is the 450-minute floor plus
  always showing raw minutes; the residual risk is a reader comparing rates
  across seasons despite the scoping.
- **Scope.** Delivered in one pass by request, so the diff will be large. Tests
  and the existing green suite are the safety net.
