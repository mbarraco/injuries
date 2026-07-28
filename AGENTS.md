# Working agreement

A UEFA injury database: a throttle-aware ingestion pipeline over the Sportmonks
API, and a FastAPI app for exploring what it collected.

This file is vendor-neutral on purpose. `CLAUDE.md` (and any other assistant's
filename) is a symlink to it, so there is one copy to keep honest.

## How we work

- **The human runs commands.** Write files and hand over the exact command to
  run; don't execute the pipeline, the migrations, or git operations unasked.
  Read-only inspection is fine.
- **`uv` runs everything.** Never bare `python`, `pip`, or `pytest`.
- **Tests are the safety net.** Run the suite before and after a change and keep
  it green. When fixing a bug, first confirm the new test fails against the old
  code — a regression test that passes either way is worthless.
- **State what was verified.** If something wasn't run, say so rather than
  implying it passed.

## Commands

```bash
uv sync                                  # install deps (pyproject.toml)
uv run pytest tests/ -q                  # the suite
uv run python -m app.etl                 # rebuild app/app.db from the raw cache
uv run uvicorn app.main:app --reload     # serve the app
```

Ingestion, in dependency order. Each is resumable and skips cached work, so
re-running is cheap and safe:

```bash
uv run python -m ingest.backfill --since 2014-01   # fixtures (--leagues to target)
uv run python -m ingest.enrich --target fixtures   # upgrade thin months
uv run python -m ingest.enrich --target players    # stats, transfers, teams
uv run python -m ingest.squads                     # team rosters
uv run python -m ingest.sync                       # incremental top-up
```

Probes and diagnostics live in `scripts/` and are read-only investigations, not
pipeline steps. The app needs `INJURY_APP_USER` and `INJURY_APP_PASSWORD` set
(via environment or the gitignored `.env`) or it refuses to serve.

## Architecture

Vendor API → **raw JSON cache** (`data/raw/`, one file per query, never
re-fetched) → **ETL** (`app/etl.py`) → **`app/app.db`** → **FastAPI**
(`app/main.py` routes, `app/queries.py` SQL, Jinja templates).

`app.db` is a rebuildable artifact, never hand-edited. The raw cache is the
durable record and outlives any subscription.

## Conventions

- **Templates render entities through `app/templates/macros.html`** —
  `entity_link`, `count_heading`, `page_link`, `stat`, `breadcrumbs`,
  `rate_empty_state`, `empty_state`. Don't hand-roll what a macro already does;
  they exist to keep behaviour identical across pages.
- **SQL is composed, never string-edited.** `_ABSENCE_PROJECTION` is
  parameterised into `_INJURY_SELECT` (the category-filtered view) and
  `_ABSENCE_SELECT` (the full table). Pick one; never `.replace()` finished SQL.
- **Every capped list returns its real total** alongside the rows, and headings
  show "N of M". A page-sized count presented as the population is a lie the
  reader can't detect.
- **Limits are named constants** at the top of their section in `queries.py`,
  so tests can shrink them to force truncation.
- **Test fixtures** live in `tests/conftest.py`: `client` and `rates_client`
  (HTTP), `connection` and `rates_connection` (query layer), plus the cache
  builders. Prefer the query-layer fixtures when asserting data rather than
  markup.
- **Progressive enhancement.** htmx is additive: forms keep `method="get"`,
  links keep real `href`s, and every page must work with JavaScript disabled.

## Invariants that fail silently

These produce plausible wrong output rather than an error. Each has a test —
if you change the behaviour, you're changing a contract:

- **`app.db` is opened read-only** (`mode=ro`). Nothing may create tables or
  indexes at request time; schema belongs in `app/schema.sql` + the ETL.
- **`/api/injuries` returns injuries only by default.** External callers depend
  on it. Add parameters; never repurpose it.
- **`/injuries` redirects to `/absences?category=injury`** with 302, not 301 —
  a permanent redirect is cached hard and effectively irreversible.
- **Pager links must extend the query string, not replace it**, or active
  filters vanish and route defaults silently take over.
- **Injury rates are scoped to one season and floored at a minimum minutes
  threshold.** Cross-season rate comparison measures vendor coverage, not
  injury risk; tiny denominators invent outliers.
- **Aggregate both sides before joining** absences to playing time. A player
  can hold several rows per season (one per club), so a naive join multiplies
  counts while the denominator stays per-club.
- **Unresolved entities render as plain text, never as a link.** Many clubs and
  players referenced by the feed are outside the subscription and have no page.

## Where the knowledge lives

- `logbook/` — vendor behaviour, measured and dated. Append-only: never edit a
  past entry; add a new one noting the correction. Read this before assuming
  anything about the API.
- `docs/dataset.md` — what the dataset is, in plain language, and the caveats
  that invalidate naive analysis.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design decisions and
  implementation plans, with the reasoning behind them.
- `docs/sportmonks/` — vendor API reference notes.

## Keeping this file honest

**Rules and pointers only — no facts.** No row counts, totals, competition
counts, or test tallies. Those rot fastest, and this repo has a track record of
stale numbers outliving their truth. Measured facts belong in the logbook and
`docs/dataset.md`, where they carry a date.
