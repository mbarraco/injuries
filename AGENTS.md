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
uv run python -m app.etl                 # rebuild app/app.db
uv run python -m app.etl_af              # rebuild app/apifootball.db
uv run uvicorn app.main:app --reload     # serve both apps (/ and /af)
```

Ingestion, in dependency order. Each is resumable and skips cached work, so
re-running is cheap and safe.

Sportmonks:

```bash
uv run python -m ingest.sportmonks.backfill --since 2014-01   # fixtures
uv run python -m ingest.sportmonks.enrich --target fixtures   # upgrade thin months
uv run python -m ingest.sportmonks.enrich --target players    # stats, transfers, teams
uv run python -m ingest.sportmonks.squads                     # team rosters
uv run python -m ingest.sportmonks.sync                       # incremental top-up
```

API-Football. Phase 0 must run first — it writes the coverage work list every
later runner iterates, and re-running it also catches coverage drift:

```bash
uv run python scripts/apifootball/af_status_and_coverage.py    # plan + work list
uv run python -m ingest.apifootball.injuries                   # the absence spine
uv run python -m ingest.apifootball.crawl --target tier1        # fixtures, teams, standings
uv run python -m ingest.apifootball.crawl --target all          # + players, team stats
uv run python -m ingest.apifootball.fixture_detail --endpoints players
uv run python -m ingest.apifootball.transfers --target team          # ~845 calls
uv run python -m ingest.apifootball.transfers --target player --include-discovered
```

The transfer crawl is ordered, not optional: `--target team` writes the files
that `--include-discovered` reads, so running the player pass first silently
covers less. Add `--dry-run` to any crawler to cost a run before spending quota.
**Run one crawler at a time** — the rate-limit pacer is per-process, so two
together aim at double the per-minute ceiling.

Probes and diagnostics live in `scripts/<vendor>/` and are read-only
investigations, not pipeline steps. The app needs `INJURY_APP_USER` and
`INJURY_APP_PASSWORD` set (via environment or the gitignored `.env`) or it
refuses to serve.

## Architecture

Vendor API → **raw JSON cache** (`data/raw/<vendor>/`, one file per query, never
re-fetched) → **ETL** → **database** → **FastAPI**.

Two vendors, deliberately not merged:

| | Sportmonks | API-Football |
|---|---|---|
| ingestion | `ingest/sportmonks/` | `ingest/apifootball/` |
| ETL | `app/etl.py` | `app/etl_af.py` |
| database | `app/app.db` | `app/apifootball.db` |
| SQL | `app/queries.py` | `app/af_queries.py` |
| routes | `app/main.py` (`/`) | `app/af_routes.py` (`/af/*`) |
| transfers | `transfer` table | `af_transfer` + `af_transfer_type` |
| templates | `app/templates/` | `app/templates/af/` |

Both databases are rebuildable artifacts, never hand-edited. The raw cache is
the durable record and outlives any subscription.

`ingest/core/` holds what is genuinely vendor-neutral (the cache, month
arithmetic). **Rate limiting is not shared** — the two APIs meter differently
enough that one abstraction would model neither correctly.

**The `/af` app is additive.** It shares `auth.py`, `base.html` and
`macros.html`; it has its own read-only connection (`db.connect_af`) and its
own `templates/af/_macros.html` for `/af/`-prefixed entity links. Changes to
the Sportmonks side must not require touching it, or vice versa.

**Do not mirror `schema.sql` into `schema_af.sql`.** The vendors' data differs
structurally, and identically-named columns would put measured values beside
inferred ones with no way to tell them apart. `schema_af.sql` documents each
divergence inline; read it before adding a column there.

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

API-Football adds its own, for reasons recorded in `logbook/apifootball.md`:

- **`apifootball.db` is opened read-only too**, same rule as `app.db`.
- **Never sum `Missing Fixture` with `Questionable`.** One is a confirmed
  absence, the other a doubt that may not have materialised. Read
  `af_confirmed_absence`, not `af_absence`, unless you mean both.
- **Absence rows are `(player, fixture)` appearances, not spells.** No spell id
  exists in this vendor's data, so one injury spanning N matches is N rows.
  Row counts here are NOT comparable to the Sportmonks `injury` view's.
- **Any spell-level figure is inferred and must carry its gap threshold.** The
  count moves ~75% across plausible thresholds. Never present one as measured.
- **Every distinct `reason` needs an `af_reason` row.** `af_injury` joins that
  table, so an unmapped reason vanishes from the view instead of showing as
  uncategorised. `af_unmapped_reason` must be empty after a rebuild.
- **The ETL refuses to build from `truncated` cache files.** A truncated
  /players file means a truncated minutes denominator, which inflates rates.
- **A player with absences may have no `af_player_season` row at all**, so
  never derive a player's total absences by summing their seasons — and their
  rate is undefined, not zero.
- **Match rate-limit responses on their wording, not the status code.** The
  vendor delivers the same condition at 429 and 200, and its rate-limit
  messages mention "plan"/"subscription" as an upsell.
- **`af_transfer` is NOT capped at 2020–2025** like every other table here. It
  is the only endpoint whose history escapes that window, so joining it to
  `af_league_season` throws most of its value away.
- **A transfer's `type` is a three-way mixed field** — a category word, a fee,
  or the vendor's `N/A`. Read `category` from `af_transfer_type`; never the raw
  string. Every distinct raw value needs a row there, same contract as
  `af_reason`: `af_unmapped_transfer_type` must be empty after a rebuild.
- **A parsed fee is inferred, and `fee_eur` is euros only.** ~18% of moves carry
  a fee at all, in three text formats. An amount the vendor left undenominated
  gets `fee_amount` but not `fee_eur`, so a euro total is a floor over a subset —
  never a market value.
- **Transfer dates are reliable to the season, not the day.** They cluster on
  1 July and on batch-stamped days. Never measure an interval in days from one.
- **Transfer dedup is an explicit counted step, not a constraint.** The vendor
  emits byte-identical duplicates, and a move between two covered clubs is
  reported by both clubs and the player. `source` records that agreement.
- **A transfer's club side may have a name and no id** — the vendor sometimes
  puts a *player* there. Render an id-less side as plain text, never a link.

## Where the knowledge lives

- `logbook/` — vendor behaviour, measured and dated. Append-only: never edit a
  past entry; add a new one noting the correction. Read this before assuming
  anything about the API.
- `docs/dataset.md` — what the dataset is, in plain language, and the caveats
  that invalidate naive analysis.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design decisions and
  implementation plans, with the reasoning behind them.
- `docs/sportmonks/` and `docs/football-api/` — vendor API reference notes.
- `app/schema_af.sql` — every place the API-Football schema diverges from
  `schema.sql`, with the measured reason inline.

## Keeping this file honest

**Rules and pointers only — no facts.** No row counts, totals, competition
counts, or test tallies. Those rot fastest, and this repo has a track record of
stale numbers outliving their truth. Measured facts belong in the logbook and
`docs/dataset.md`, where they carry a date.
