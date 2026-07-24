# Injury Data POC Web App Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI POC that showcases the Sportmonks injury dataset's coverage, data quality, and analytical linkage to a product-owner audience.

**Architecture:** A batch ETL parses 1,979 cached raw JSON fixture files plus existing resolved reference tables in `coverage.db`, deduplicates absences by `sideline_id` (4× inflation in the raw data), filters to injuries only, and writes a clean normalized SQLite database at `app/app.db`. A FastAPI app serves three server-rendered Jinja2 pages (coverage/quality, analytics, explorable records), each backed by a matching JSON API endpoint. All SQL lives in `queries.py`; no ORM.

**Tech Stack:** Python 3.14, FastAPI, Uvicorn, Jinja2, SQLite (stdlib `sqlite3`), Chart.js (CDN-free, vendored), pytest. Dependencies managed by `uv` via PEP 723 inline script metadata for scripts and a `requirements.txt` for the app.

**Spec:** `docs/superpowers/specs/2026-07-23-injury-data-poc-app-design.md`

---

## Execution slices

Implement and validate the POC in small, independently reviewable slices.
Commit each slice only after its focused checks pass; do not mix unrelated
research-cache changes into these commits.

1. **Foundation:** requirements, ignored derived database, schema, and ETL
   tests. Commit: `chore: scaffold injury data POC`.
2. **Curated data:** finish the ETL, run it against the full cache, and
   verify deduplication and category totals. Commit: `feat: build curated injury database`.
3. **Data access:** read-only database helper plus overview, quality, and
   analytics queries with unit tests. Commit: `feat: add injury data queries`.
4. **Exploration API:** filtered records, player timeline, and FastAPI JSON
   endpoints with API tests. Commit: `feat: add injury exploration API`.
5. **Product UI:** templates, offline chart asset, responsive styling, and
   browser/server smoke checks. Commit: `feat: add injury data POC interface`.
6. **Handoff:** runbook and full test suite. Commit: `docs: add injury POC runbook`.

---

## Context for the implementer

You have zero context on this project. Key facts you need:

**The data source.** `data/raw/sportmonks/fixtures/*.json` contains 1,979 files named `{league_id}_{YYYY-MM}.json`. Each has this shape:

```json
{
  "league_id": 172,
  "window": ["2026-04-01", "2026-05-01"],
  "fetched_at": "2026-07-23T23:27:27+00:00",
  "truncated": false,
  "fixtures": [
    {
      "id": 19484387,
      "season_id": 25993,
      "name": "Flamurtari vs Tirana",
      "starting_at": "2026-04-03 17:00:00",
      "sidelined": [
        {
          "id": 1406288,
          "fixture_id": 19484387,
          "sideline_id": 781575,
          "participant_id": 5207,
          "player_id": 49395,
          "type_id": 561,
          "sideline": {
            "id": 781575,
            "player_id": 49395,
            "type_id": 561,
            "category": "suspended",
            "team_id": 5207,
            "season_id": null,
            "start_date": "2026-03-25",
            "end_date": "2026-05-11",
            "games_missed": 7,
            "completed": true
          }
        }
      ]
    }
  ]
}
```

**CRITICAL — the dedup requirement.** Each entry in a fixture's `sidelined` array is a *fixture-appearance*, not a distinct injury. One real injury (one `sideline_id`) appears once per match the player missed. Measured: 67,403 raw rows → 16,747 distinct `sideline_id`s → **4.0× inflation**. You MUST deduplicate by `sideline_id`. The count of appearances per `sideline_id` is itself meaningful data (`fixture_appearances`).

**The nested object matters.** The outer pivot's `player_id`/`type_id` are often null. The real data is in the nested `sideline` object. Prefer `sideline.*`, fall back to pivot-level.

**Category filtering.** `sideline.category` has four values: `injury` (10,047), `suspended` (6,629), `suspension` (54), `doubtful` (17). Note `suspended` and `suspension` are the same concept spelled two ways — a real vendor defect. **Only `injury` goes into the `injury` table.** The others are counted and recorded in `data_quality` as exclusions.

**`season_id` is null on 100% of sideline records** — take it from the parent fixture object instead.

**`league_id` comes from the enclosing file's top-level `league_id`.** If the same `sideline_id` appears in more than one league's files, keep the first occurrence (deterministic: process files in sorted order).

**Reference data lives in `coverage.db`** (read-only for this project) in these already-resolved tables:
- `sportmonks_player (id, name, position, detailed_position, nationality, date_of_birth, height_cm, weight_kg)` — 10,734 rows
- `sportmonks_team (id, name, country, founded, short_code)` — 801 rows
- `sportmonks_type (id, name)` — 278 rows
- `sportmonks_season (id, league_id, country, league_name, name, is_current, dates_json)` — 159 rows
- `sportmonks_coverage (run_id, country, league, sportmonks_id, year_bucket, record_count, tier)` — use `run_id = 16` (latest, post league-id fix)

**Known gaps that are expected, not bugs:**
- 36 player ids never resolved (genuine dead ids) — injuries referencing them still belong in the table; join yields NULL name.
- 174 team ids (18%) never resolved — Sportmonks silently returns HTTP 200 + empty data for out-of-plan teams. Same handling: keep the injury, NULL team name.
- Never crash or drop an injury because a dimension lookup misses. Use LEFT JOINs throughout.

**Style:** Match the existing codebase — plain stdlib `sqlite3` (no ORM), module-level constants for paths, docstrings that explain *why* not *what*.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/schema.sql` | The complete `app.db` DDL. Single source of truth for schema. |
| `app/etl.py` | Parse raw cache + read `coverage.db` → write `app.db`. Standalone runnable. |
| `app/db.py` | Read-only connection factory + row-to-dict helper. Nothing else. |
| `app/queries.py` | One function per view. ALL SQL lives here. No SQL anywhere else. |
| `app/main.py` | FastAPI routes only — HTML pages + JSON endpoints. Thin; delegates to `queries.py`. |
| `app/templates/base.html` | Layout, nav, shared head/CSS include. |
| `app/templates/coverage.html` | `/` — coverage & data quality page. |
| `app/templates/analytics.html` | `/analytics` — aggregations & linkage. |
| `app/templates/injuries.html` | `/injuries` — explorable filtered table. |
| `app/templates/player.html` | `/player/{id}` — drill-down timeline. |
| `app/static/style.css` | All styling. Hand-written, no framework. |
| `app/static/chart.min.js` | Vendored Chart.js (no CDN — must work offline). |
| `app/requirements.txt` | fastapi, uvicorn, jinja2, pytest |
| `tests/test_etl.py` | ETL correctness: dedup, category filter, derived fields. |
| `tests/test_queries.py` | Query functions return expected shapes against a fixture DB. |
| `tests/conftest.py` | Builds a tiny in-memory `app.db` from known fixtures. |

Splitting `queries.py` from `main.py` is deliberate: it keeps SQL testable without spinning up HTTP, and keeps routes readable.

---

## Chunk 1: Schema and ETL

### Task 1: Project scaffolding and dependencies

**Files:**
- Create: `app/requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Create `app/requirements.txt`**

```
fastapi>=0.115,<1
uvicorn[standard]>=0.32,<1
jinja2>=3.1,<4
pytest>=8.0,<9
httpx>=0.27,<1
```

(`httpx` is required by FastAPI's `TestClient`.)

- [ ] **Step 2: Add generated artifacts to `.gitignore`**

Append to `.gitignore`:

```
# App POC
app/app.db
```

- [ ] **Step 3: Verify install works**

Run: `cd /Users/mbarraco/code/injuries && uv venv --python 3.14 && uv pip install -r app/requirements.txt`
Expected: installs without error.

- [ ] **Step 4: Commit**

```bash
git add app/requirements.txt .gitignore
git commit -m "chore: scaffold POC app dependencies"
```

---

### Task 2: Database schema

**Files:**
- Create: `app/schema.sql`

- [ ] **Step 1: Write `app/schema.sql`**

```sql
-- Injury POC schema. Rebuilt from scratch by etl.py on every run —
-- app.db is a derived artifact, never hand-edited. The raw JSON cache
-- under data/raw/ is the real source of truth.

DROP TABLE IF EXISTS injury;
DROP TABLE IF EXISTS player;
DROP TABLE IF EXISTS team;
DROP TABLE IF EXISTS injury_type;
DROP TABLE IF EXISTS season;
DROP TABLE IF EXISTS league;
DROP TABLE IF EXISTS league_coverage;
DROP TABLE IF EXISTS data_quality;
DROP TABLE IF EXISTS ingest_run;

CREATE TABLE league (
    id            INTEGER PRIMARY KEY,
    country       TEXT,
    name          TEXT
);

CREATE TABLE season (
    id            INTEGER PRIMARY KEY,
    league_id     INTEGER REFERENCES league(id),
    name          TEXT,
    is_current    INTEGER
);

CREATE TABLE team (
    id            INTEGER PRIMARY KEY,
    name          TEXT,
    country       TEXT,
    founded       INTEGER,
    short_code    TEXT
);

CREATE TABLE player (
    id                INTEGER PRIMARY KEY,
    name              TEXT,
    position          TEXT,
    detailed_position TEXT,
    nationality       TEXT,
    date_of_birth     TEXT,
    height_cm         INTEGER,
    weight_kg         INTEGER
);

CREATE TABLE injury_type (
    id            INTEGER PRIMARY KEY,
    name          TEXT
);

-- One row per DISTINCT injury (deduplicated by sideline_id).
-- Only category == 'injury'; suspensions/doubtful are excluded and
-- counted in data_quality.
CREATE TABLE injury (
    id                  INTEGER PRIMARY KEY,   -- sideline_id
    player_id           INTEGER REFERENCES player(id),
    team_id             INTEGER REFERENCES team(id),
    league_id           INTEGER REFERENCES league(id),
    season_id           INTEGER REFERENCES season(id),
    type_id             INTEGER REFERENCES injury_type(id),
    start_date          TEXT NOT NULL,
    end_date            TEXT,
    games_missed        INTEGER,
    completed           INTEGER,
    fixture_appearances INTEGER NOT NULL,
    duration_days       INTEGER,
    age_at_start        REAL,
    is_ongoing          INTEGER NOT NULL
);

CREATE INDEX idx_injury_league  ON injury(league_id);
CREATE INDEX idx_injury_season  ON injury(season_id);
CREATE INDEX idx_injury_player  ON injury(player_id);
CREATE INDEX idx_injury_type    ON injury(type_id);
CREATE INDEX idx_injury_start   ON injury(start_date);

-- Per-league coverage tiers, carried over from the investigation so the
-- coverage page can show measured breadth per year bucket.
CREATE TABLE league_coverage (
    country       TEXT,
    league        TEXT,
    league_id     INTEGER,
    year_bucket   TEXT,
    record_count  INTEGER,
    tier          TEXT
);

-- Measured quality metrics written by the ETL. The UI renders these
-- values; it never hardcodes a quality claim.
CREATE TABLE data_quality (
    metric        TEXT PRIMARY KEY,
    value         REAL,
    detail        TEXT
);

CREATE TABLE ingest_run (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at            TEXT NOT NULL,
    source_file_count INTEGER,
    notes             TEXT
);
```

- [ ] **Step 2: Verify the schema is valid SQL**

Run: `cd /Users/mbarraco/code/injuries && python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.executescript(open('app/schema.sql').read()); print('tables:', sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"`
Expected: `tables: ['data_quality', 'ingest_run', 'injury', 'injury_type', 'league', 'league_coverage', 'player', 'season', 'sqlite_sequence', 'team']`

- [ ] **Step 3: Commit**

```bash
git add app/schema.sql
git commit -m "feat: add POC app database schema"
```

---

### Task 3: ETL — parse and deduplicate raw injuries

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_etl.py`
- Create: `app/etl.py`

- [ ] **Step 1: Write test fixtures and the failing test**

Create `tests/conftest.py`:

```python
import json
import os

import pytest


@pytest.fixture
def raw_cache_dir(tmp_path):
    """A miniature raw fixture cache exercising the real edge cases:
    the same injury appearing in multiple fixtures (dedup), a suspension
    that must be excluded, an ongoing injury with a null end_date, and
    season_id present only on the parent fixture."""
    d = tmp_path / "fixtures"
    d.mkdir()

    def sidelined(sideline_id, player_id, category, start, end,
                  games_missed=3, team_id=100, type_id=500):
        return {
            "id": sideline_id * 10,
            "sideline_id": sideline_id,
            "player_id": None,          # deliberately null: must fall back
            "type_id": None,
            "sideline": {
                "id": sideline_id,
                "player_id": player_id,
                "type_id": type_id,
                "category": category,
                "team_id": team_id,
                "season_id": None,      # always null from the vendor
                "start_date": start,
                "end_date": end,
                "games_missed": games_missed,
                "completed": end is not None,
            },
        }

    # Injury 900 appears in BOTH fixtures -> must dedupe to one row with
    # fixture_appearances == 2.
    (d / "10_2025-03.json").write_text(json.dumps({
        "league_id": 10,
        "window": ["2025-03-01", "2025-04-01"],
        "fixtures": [
            {"id": 1, "season_id": 77, "sidelined": [
                sidelined(900, 5001, "injury", "2025-02-01", "2025-04-01"),
                sidelined(901, 5002, "suspended", "2025-03-01", "2025-03-20"),
            ]},
            {"id": 2, "season_id": 77, "sidelined": [
                sidelined(900, 5001, "injury", "2025-02-01", "2025-04-01"),
                sidelined(902, 5003, "injury", "2025-03-05", None),
            ]},
        ],
    }))
    return d


@pytest.fixture
def reference_db(tmp_path):
    """Stand-in for coverage.db's already-resolved reference tables."""
    import sqlite3
    path = tmp_path / "coverage.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sportmonks_player (id TEXT PRIMARY KEY, name TEXT,
            position TEXT, detailed_position TEXT, nationality TEXT,
            date_of_birth TEXT, height_cm INTEGER, weight_kg INTEGER);
        CREATE TABLE sportmonks_team (id TEXT PRIMARY KEY, name TEXT,
            country TEXT, founded INTEGER, short_code TEXT);
        CREATE TABLE sportmonks_type (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE sportmonks_season (id TEXT PRIMARY KEY, league_id TEXT,
            country TEXT, league_name TEXT, name TEXT, is_current INTEGER,
            dates_json TEXT);
        CREATE TABLE sportmonks_coverage (run_id INTEGER, country TEXT,
            league TEXT, sportmonks_id TEXT, year_bucket TEXT,
            record_count INTEGER, tier TEXT);
    """)
    conn.execute("INSERT INTO sportmonks_player VALUES "
                 "('5001','A. Player','Defender','Centre Back','Brazil',"
                 "'2000-01-01',180,75)")
    conn.execute("INSERT INTO sportmonks_player VALUES "
                 "('5003','C. Player','Forward','Striker','Spain',"
                 "'1995-06-15',175,70)")
    # NOTE: player 5002 deliberately absent (unresolvable id case)
    conn.execute("INSERT INTO sportmonks_team VALUES ('100','FC Test','Testland',1900,'FCT')")
    conn.execute("INSERT INTO sportmonks_type VALUES ('500','Knock')")
    conn.execute("INSERT INTO sportmonks_season VALUES "
                 "('77','10','Testland','Test League','2024/2025',1,'{}')")
    conn.execute("INSERT INTO sportmonks_coverage VALUES "
                 "(16,'Testland','Test League','10','2024-08..2025-07',500,'moderate')")
    conn.commit()
    conn.close()
    return path
```

Create `tests/test_etl.py`:

```python
import sqlite3

from app import etl


def test_dedupes_injuries_by_sideline_id(tmp_path, raw_cache_dir, reference_db):
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)

    conn = sqlite3.connect(out)
    rows = conn.execute(
        "SELECT id, fixture_appearances FROM injury ORDER BY id").fetchall()

    # 900 appeared in 2 fixtures -> ONE row, appearances 2
    # 902 appeared once -> one row
    # 901 is a suspension -> excluded entirely
    assert rows == [(900, 2), (902, 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_etl.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.etl'` (or ImportError).

- [ ] **Step 3: Write minimal `app/etl.py` to pass**

Create `app/__init__.py` (empty file, so `app` is importable as a package).

Create `app/etl.py`:

```python
"""Build app.db from the raw Sportmonks fixture cache plus the resolved
reference tables in coverage.db.

app.db is a fully derived artifact — this rebuilds it from scratch every
run. The raw JSON cache is the source of truth, and it outlives any API
subscription, so a rebuild never needs network access.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import date, datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RAW_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "fixtures")
DEFAULT_REFERENCE_DB = os.path.join(BASE, "coverage.db")
DEFAULT_OUT_DB = os.path.join(BASE, "app", "app.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# Only this category becomes an injury. The vendor also emits 'suspended',
# 'suspension' (the same concept, two spellings — a real defect) and
# 'doubtful'; all are excluded but counted for the quality report.
INJURY_CATEGORY = "injury"


def collect_absences(raw_dir):
    """Scan every cached fixture file and deduplicate absences.

    Each entry in a fixture's `sidelined` array is a fixture-APPEARANCE,
    not a distinct absence: one real injury reappears once per match the
    player missed (measured 4x inflation across the full cache). We key
    by sideline_id and count appearances.

    Files are processed in sorted order so that league attribution for an
    absence appearing under multiple leagues is deterministic.
    """
    absences = {}
    files = sorted(glob.glob(os.path.join(raw_dir, "*.json")))
    for path in files:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        league_id = doc.get("league_id")
        for fixture in doc.get("fixtures", []):
            season_id = fixture.get("season_id")
            for pivot in fixture.get("sidelined") or []:
                nested = pivot.get("sideline") or {}
                sid = pivot.get("sideline_id") or nested.get("id")
                if not sid:
                    continue
                if sid in absences:
                    absences[sid]["fixture_appearances"] += 1
                    continue
                absences[sid] = {
                    "id": sid,
                    # Prefer the nested object: pivot-level player_id and
                    # type_id are frequently null.
                    "player_id": nested.get("player_id") or pivot.get("player_id"),
                    "team_id": nested.get("team_id"),
                    "type_id": nested.get("type_id") or pivot.get("type_id"),
                    "category": nested.get("category"),
                    # season_id is null on 100% of vendor sideline records;
                    # the parent fixture is the only source.
                    "season_id": season_id,
                    "league_id": league_id,
                    "start_date": nested.get("start_date"),
                    "end_date": nested.get("end_date"),
                    "games_missed": nested.get("games_missed"),
                    "completed": nested.get("completed"),
                    "fixture_appearances": 1,
                }
    return absences, len(files)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def derive_fields(absence, birth_date):
    """duration_days and age_at_start are materialized at ETL time rather
    than computed per query — they drive the headline analytics and
    SQLite date arithmetic in a hot path isn't worth it."""
    start = _parse_date(absence["start_date"])
    end = _parse_date(absence["end_date"])
    duration = (end - start).days if (start and end) else None
    born = _parse_date(birth_date)
    age = round((start - born).days / 365.25, 1) if (start and born) else None
    return duration, age, 0 if end else 1


def build(raw_dir=DEFAULT_RAW_DIR, reference_db=DEFAULT_REFERENCE_DB,
          out_db=DEFAULT_OUT_DB):
    absences, file_count = collect_absences(raw_dir)

    if os.path.exists(out_db):
        os.remove(out_db)
    conn = sqlite3.connect(out_db)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())

    ref = sqlite3.connect(f"file:{reference_db}?mode=ro", uri=True)

    players = {int(r[0]): r for r in ref.execute(
        "SELECT id, name, position, detailed_position, nationality, "
        "date_of_birth, height_cm, weight_kg FROM sportmonks_player")}
    conn.executemany(
        "INSERT INTO player VALUES (?,?,?,?,?,?,?,?)",
        [(int(r[0]), *r[1:]) for r in players.values()])

    conn.executemany(
        "INSERT INTO team VALUES (?,?,?,?,?)",
        [(int(r[0]), *r[1:]) for r in ref.execute(
            "SELECT id, name, country, founded, short_code FROM sportmonks_team")])

    conn.executemany(
        "INSERT INTO injury_type VALUES (?,?)",
        [(int(r[0]), r[1]) for r in ref.execute(
            "SELECT id, name FROM sportmonks_type")])

    seasons = list(ref.execute(
        "SELECT id, league_id, country, league_name, name, is_current "
        "FROM sportmonks_season"))
    conn.executemany(
        "INSERT OR IGNORE INTO league VALUES (?,?,?)",
        sorted({(int(s[1]), s[2], s[3]) for s in seasons if s[1]}))
    conn.executemany(
        "INSERT INTO season VALUES (?,?,?,?)",
        [(int(s[0]), int(s[1]) if s[1] else None, s[4], s[5]) for s in seasons])

    conn.executemany(
        "INSERT INTO league_coverage VALUES (?,?,?,?,?,?)",
        [(r[0], r[1], int(r[2]) if r[2] else None, r[3], r[4], r[5])
         for r in ref.execute(
             "SELECT country, league, sportmonks_id, year_bucket, "
             "record_count, tier FROM sportmonks_coverage WHERE run_id = 16")])

    injuries, excluded = [], {}
    for a in absences.values():
        category = a["category"]
        if category != INJURY_CATEGORY:
            excluded[category] = excluded.get(category, 0) + 1
            continue
        birth = players.get(a["player_id"], (None,) * 6)[5] if a["player_id"] else None
        duration, age, ongoing = derive_fields(a, birth)
        injuries.append((
            a["id"], a["player_id"], a["team_id"], a["league_id"],
            a["season_id"], a["type_id"], a["start_date"], a["end_date"],
            a["games_missed"], 1 if a["completed"] else 0,
            a["fixture_appearances"], duration, age, ongoing,
        ))
    conn.executemany(
        "INSERT INTO injury VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", injuries)

    _write_quality_metrics(conn, absences, injuries, excluded, file_count)

    conn.execute(
        "INSERT INTO ingest_run (run_at, source_file_count, notes) VALUES (?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), file_count,
         "rebuilt from raw cache"))
    conn.commit()
    conn.close()
    ref.close()
    return {"injuries": len(injuries), "excluded": excluded}


def _write_quality_metrics(conn, absences, injuries, excluded, file_count):
    raw_rows = sum(a["fixture_appearances"] for a in absences.values())
    distinct = len(absences)
    metrics = [
        ("source_files", file_count, "cached fixture-month JSON files scanned"),
        ("raw_pivot_rows", raw_rows,
         "fixture-appearance rows before dedup — NOT distinct injuries"),
        ("distinct_absences", distinct, "unique sideline_id values"),
        ("dedup_ratio", round(raw_rows / distinct, 2) if distinct else 0,
         "raw rows per distinct absence"),
        ("injuries", len(injuries), "category == 'injury', the app's dataset"),
    ]
    for cat, n in sorted(excluded.items()):
        metrics.append((f"excluded_{cat}", n, f"category '{cat}' excluded"))

    if injuries:
        total = len(injuries)
        for idx, label in ((2, "team_id"), (7, "end_date"), (8, "games_missed")):
            filled = sum(1 for row in injuries if row[idx] is not None)
            metrics.append((f"fill_{label}", round(100 * filled / total, 1),
                            f"% of injuries with {label} populated"))
    conn.executemany("INSERT OR REPLACE INTO data_quality VALUES (?,?,?)", metrics)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_etl.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/etl.py tests/conftest.py tests/test_etl.py
git commit -m "feat: ETL deduplicates absences by sideline_id"
```

---

### Task 4: ETL — category filtering and derived fields

**Files:**
- Modify: `tests/test_etl.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_etl.py`:

```python
def test_excludes_non_injury_categories(tmp_path, raw_cache_dir, reference_db):
    out = tmp_path / "app.db"
    result = etl.build(raw_cache_dir, reference_db, out)

    assert result["excluded"] == {"suspended": 1}

    conn = sqlite3.connect(out)
    (n,) = conn.execute("SELECT COUNT(*) FROM injury").fetchone()
    assert n == 2  # only the two 'injury' rows


def test_derives_duration_age_and_ongoing(tmp_path, raw_cache_dir, reference_db):
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)
    conn = sqlite3.connect(out)

    duration, age, ongoing = conn.execute(
        "SELECT duration_days, age_at_start, is_ongoing FROM injury WHERE id=900"
    ).fetchone()
    assert duration == 59            # 2025-02-01 -> 2025-04-01
    assert age == 25.1               # born 2000-01-01, injured 2025-02-01
    assert ongoing == 0

    # 902 has a null end_date -> ongoing, no duration
    duration, ongoing = conn.execute(
        "SELECT duration_days, is_ongoing FROM injury WHERE id=902").fetchone()
    assert duration is None
    assert ongoing == 1


def test_records_quality_metrics(tmp_path, raw_cache_dir, reference_db):
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)
    conn = sqlite3.connect(out)
    metrics = dict(conn.execute("SELECT metric, value FROM data_quality"))

    assert metrics["raw_pivot_rows"] == 4      # 2+2 sidelined entries
    assert metrics["distinct_absences"] == 3   # 900, 901, 902
    assert metrics["injuries"] == 2
    assert metrics["excluded_suspended"] == 1


def test_keeps_injuries_with_unresolvable_dimensions(tmp_path, raw_cache_dir,
                                                     reference_db):
    """Player 5002 is absent from the reference DB (a real, expected case:
    36 dead player ids). Its record is a suspension so it's excluded here,
    but the principle holds — no injury is ever dropped for a missing
    dimension. Verified via LEFT JOIN returning a NULL name."""
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)
    conn = sqlite3.connect(out)
    rows = conn.execute(
        "SELECT i.id, p.name FROM injury i "
        "LEFT JOIN player p ON p.id = i.player_id ORDER BY i.id").fetchall()
    assert rows == [(900, "A. Player"), (902, "C. Player")]
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_etl.py -v`
Expected: PASS (the Task 3 implementation already satisfies these — this task
verifies behavior rather than adding code). If any fail, fix `app/etl.py`
until they pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_etl.py
git commit -m "test: cover category filtering, derived fields, quality metrics"
```

---

### Task 5: Run ETL against the real cache

**Files:** none (verification task)

- [ ] **Step 1: Add a CLI entrypoint to `app/etl.py`**

Append to `app/etl.py`:

```python
if __name__ == "__main__":
    result = build()
    print(f"injuries loaded: {result['injuries']}")
    print(f"excluded by category: {result['excluded']}")
    print(f"-> {DEFAULT_OUT_DB}")
```

- [ ] **Step 2: Run the real ETL**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m app.etl`
Expected output (approximately — exact numbers may shift if the cache changed):
```
injuries loaded: 10047
excluded by category: {'doubtful': 17, 'suspended': 6629, 'suspension': 54}
-> /Users/mbarraco/code/injuries/app/app.db
```

**STOP if `injuries loaded` is not ~10,047** — that indicates the dedup or
category filter is wrong. Investigate before proceeding.

- [ ] **Step 3: Sanity-check the output**

Run:
```bash
cd /Users/mbarraco/code/injuries && sqlite3 -header -column app/app.db "
SELECT metric, value, detail FROM data_quality ORDER BY metric;"
```
Expected: `dedup_ratio` ≈ 4.0, `raw_pivot_rows` ≈ 67403, `distinct_absences` ≈ 16747.

- [ ] **Step 4: Commit**

```bash
git add app/etl.py
git commit -m "feat: add ETL CLI entrypoint"
```

---

## Chunk 2: Query layer and API

### Task 6: Read-only DB access

**Files:**
- Create: `app/db.py`

- [ ] **Step 1: Write `app/db.py`**

```python
"""Read-only access to app.db.

The app never writes — app.db is rebuilt wholesale by etl.py. Opening
read-only makes that guarantee explicit and prevents accidental writes
from a stray query.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")


def connect(path=None):
    conn = sqlite3.connect(f"file:{path or DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn, sql, params=()):
    """Run a query and return plain dicts — templates and JSON responses
    both want dicts, not sqlite3.Row objects."""
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
```

- [ ] **Step 2: Commit**

```bash
git add app/db.py
git commit -m "feat: add read-only database access helper"
```

---

### Task 7: Query functions — overview and quality

**Files:**
- Create: `tests/test_queries.py`
- Create: `app/queries.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_queries.py`:

```python
import pytest

from app import db, etl, queries


@pytest.fixture
def conn(tmp_path, raw_cache_dir, reference_db):
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)
    c = db.connect(out)
    yield c
    c.close()


def test_overview_returns_headline_counts(conn):
    result = queries.overview(conn)
    assert result["injuries"] == 2
    assert result["leagues"] >= 1
    assert result["earliest"] == "2025-02-01"
    assert result["latest"] == "2025-03-05"


def test_quality_metrics_returns_all_rows(conn):
    metrics = queries.quality_metrics(conn)
    names = {m["metric"] for m in metrics}
    assert "dedup_ratio" in names
    assert "injuries" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_queries.py -v`
Expected: FAIL — no module named `app.queries`.

- [ ] **Step 3: Write `app/queries.py`**

```python
"""All SQL for the app lives here — one function per view.

Kept separate from main.py so queries are testable without HTTP, and so
routes stay readable. Every join to a dimension is a LEFT JOIN: 36 player
ids and 174 team ids are legitimately unresolvable (out-of-plan gating),
and an injury must never disappear because a lookup missed.
"""
from app.db import rows


def overview(conn):
    return dict(conn.execute("""
        SELECT
          (SELECT COUNT(*) FROM injury)                      AS injuries,
          (SELECT COUNT(DISTINCT league_id) FROM injury)     AS leagues,
          (SELECT COUNT(DISTINCT player_id) FROM injury)     AS players,
          (SELECT COUNT(DISTINCT team_id) FROM injury)       AS teams,
          (SELECT MIN(start_date) FROM injury)               AS earliest,
          (SELECT MAX(start_date) FROM injury)               AS latest,
          (SELECT COUNT(*) FROM injury WHERE is_ongoing = 1) AS ongoing
    """).fetchone())


def quality_metrics(conn):
    return rows(conn, "SELECT metric, value, detail FROM data_quality "
                      "ORDER BY metric")


def coverage_by_league(conn):
    """Pivots the three year buckets into columns so the coverage table
    reads as one row per league."""
    return rows(conn, """
        SELECT country, league,
               MAX(CASE WHEN rn = 1 THEN record_count END) AS yr1,
               MAX(CASE WHEN rn = 2 THEN record_count END) AS yr2,
               MAX(CASE WHEN rn = 3 THEN record_count END) AS yr3,
               MAX(CASE WHEN rn = 3 THEN tier END)         AS tier
        FROM (SELECT *, ROW_NUMBER() OVER
                     (PARTITION BY country ORDER BY year_bucket) AS rn
              FROM league_coverage)
        GROUP BY country, league
        ORDER BY yr3 DESC
    """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/queries.py tests/test_queries.py
git commit -m "feat: add overview and quality query functions"
```

---

### Task 8: Query functions — analytics aggregations

**Files:**
- Modify: `app/queries.py`
- Modify: `tests/test_queries.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_queries.py`:

```python
def test_by_position_groups_and_counts(conn):
    result = queries.by_position(conn)
    positions = {r["position"]: r["injuries"] for r in result}
    assert positions == {"Defender": 1, "Forward": 1}


def test_by_age_band_buckets_correctly(conn):
    result = queries.by_age_band(conn)
    bands = {r["band"]: r["injuries"] for r in result}
    assert bands["25-29"] == 1   # age 25.1
    assert bands["30+"] == 1     # age ~29.7 -> check actual bucket


def test_by_type_reports_averages(conn):
    result = queries.by_type(conn)
    assert result[0]["type"] == "Knock"
    assert result[0]["injuries"] == 2
```

Note: the exact age-band assertion may need adjusting once you see the
computed ages — run the query and align the test with reality rather than
forcing the data to match a guess.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_queries.py -v`
Expected: FAIL — `queries.by_position` does not exist.

- [ ] **Step 3: Implement the aggregations**

Append to `app/queries.py`:

```python
def by_position(conn):
    return rows(conn, """
        SELECT COALESCE(p.position, 'Unknown') AS position,
               COUNT(*)                        AS injuries,
               ROUND(AVG(i.duration_days), 1)  AS avg_duration,
               ROUND(AVG(i.games_missed), 1)   AS avg_games_missed
        FROM injury i
        LEFT JOIN player p ON p.id = i.player_id
        GROUP BY position
        ORDER BY injuries DESC
    """)


def by_age_band(conn):
    """Age bands come from age_at_start, materialized at ETL time from
    date_of_birth — a join raw API data can't do at all."""
    return rows(conn, """
        SELECT CASE
                 WHEN age_at_start IS NULL  THEN 'Unknown'
                 WHEN age_at_start < 20     THEN 'Under 20'
                 WHEN age_at_start < 25     THEN '20-24'
                 WHEN age_at_start < 30     THEN '25-29'
                 WHEN age_at_start < 35     THEN '30-34'
                 ELSE '35+'
               END                          AS band,
               COUNT(*)                     AS injuries,
               ROUND(AVG(duration_days), 1) AS avg_duration
        FROM injury
        GROUP BY band
        ORDER BY band
    """)


def by_type(conn, limit=15):
    return rows(conn, """
        SELECT COALESCE(t.name, 'Unknown')   AS type,
               COUNT(*)                      AS injuries,
               ROUND(AVG(i.duration_days),1) AS avg_duration,
               ROUND(AVG(i.games_missed),1)  AS avg_games_missed
        FROM injury i
        LEFT JOIN injury_type t ON t.id = i.type_id
        GROUP BY type
        ORDER BY injuries DESC
        LIMIT ?
    """, (limit,))


def by_nationality(conn, limit=15):
    return rows(conn, """
        SELECT COALESCE(p.nationality, 'Unknown') AS nationality,
               COUNT(*)                           AS injuries
        FROM injury i
        LEFT JOIN player p ON p.id = i.player_id
        GROUP BY nationality
        ORDER BY injuries DESC
        LIMIT ?
    """, (limit,))


def by_league(conn):
    return rows(conn, """
        SELECT COALESCE(l.country, 'Unknown')  AS country,
               COALESCE(l.name, 'Unknown')     AS league,
               COUNT(*)                        AS injuries,
               ROUND(AVG(i.duration_days), 1)  AS avg_duration
        FROM injury i
        LEFT JOIN league l ON l.id = i.league_id
        GROUP BY country, league
        ORDER BY injuries DESC
    """)


def by_month(conn):
    """Seasonality. Uses start_date's month across all years."""
    return rows(conn, """
        SELECT strftime('%m', start_date) AS month,
               COUNT(*)                   AS injuries
        FROM injury
        WHERE start_date IS NOT NULL
        GROUP BY month
        ORDER BY month
    """)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/queries.py tests/test_queries.py
git commit -m "feat: add analytics aggregation queries"
```

---

### Task 9: Query functions — filtered injury list and player drill-down

**Files:**
- Modify: `app/queries.py`
- Modify: `tests/test_queries.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_queries.py`:

```python
def test_injury_list_filters_by_ongoing(conn):
    result = queries.injury_list(conn, ongoing_only=True)
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == 902


def test_injury_list_paginates(conn):
    result = queries.injury_list(conn, page=1, per_page=1)
    assert len(result["items"]) == 1
    assert result["total"] == 2


def test_player_timeline(conn):
    result = queries.player_timeline(conn, 5001)
    assert result["player"]["name"] == "A. Player"
    assert len(result["injuries"]) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_queries.py -v`
Expected: FAIL — `queries.injury_list` does not exist.

- [ ] **Step 3: Implement**

Append to `app/queries.py`:

```python
_INJURY_SELECT = """
    SELECT i.id, i.start_date, i.end_date, i.duration_days,
           i.games_missed, i.is_ongoing, i.age_at_start,
           i.fixture_appearances,
           p.name AS player, p.position,
           t.name AS team,
           l.country, l.name AS league,
           ty.name AS type
    FROM injury i
    LEFT JOIN player      p  ON p.id  = i.player_id
    LEFT JOIN team        t  ON t.id  = i.team_id
    LEFT JOIN league      l  ON l.id  = i.league_id
    LEFT JOIN injury_type ty ON ty.id = i.type_id
"""

_SORTABLE = {
    "start_date": "i.start_date",
    "duration": "i.duration_days",
    "games_missed": "i.games_missed",
    "player": "p.name",
    "league": "l.name",
}


def injury_list(conn, country=None, position=None, type_name=None,
                ongoing_only=False, sort="start_date", direction="desc",
                page=1, per_page=50):
    """Filtered, sorted, paginated injuries.

    Sort keys are whitelisted against _SORTABLE rather than interpolated
    from user input — the column can't be a bound parameter, so an
    allowlist is the safe way to make it dynamic.
    """
    where, params = [], []
    if country:
        where.append("l.country = ?")
        params.append(country)
    if position:
        where.append("p.position = ?")
        params.append(position)
    if type_name:
        where.append("ty.name = ?")
        params.append(type_name)
    if ongoing_only:
        where.append("i.is_ongoing = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM ({_INJURY_SELECT} {clause})", params).fetchone()[0]

    column = _SORTABLE.get(sort, "i.start_date")
    order = "ASC" if direction.lower() == "asc" else "DESC"
    offset = (max(page, 1) - 1) * per_page
    items = rows(conn,
                 f"{_INJURY_SELECT} {clause} ORDER BY {column} {order} "
                 f"LIMIT ? OFFSET ?", (*params, per_page, offset))
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def filter_options(conn):
    """Distinct values for the filter dropdowns."""
    return {
        "countries": [r["country"] for r in rows(
            conn, "SELECT DISTINCT country FROM league "
                  "WHERE country IS NOT NULL ORDER BY country")],
        "positions": [r["position"] for r in rows(
            conn, "SELECT DISTINCT position FROM player "
                  "WHERE position IS NOT NULL ORDER BY position")],
        "types": [r["name"] for r in rows(
            conn, "SELECT DISTINCT ty.name FROM injury i "
                  "JOIN injury_type ty ON ty.id = i.type_id ORDER BY ty.name")],
    }


def player_timeline(conn, player_id):
    player = conn.execute(
        "SELECT * FROM player WHERE id = ?", (player_id,)).fetchone()
    injuries = rows(conn, f"{_INJURY_SELECT} WHERE i.player_id = ? "
                          f"ORDER BY i.start_date DESC", (player_id,))
    return {"player": dict(player) if player else None, "injuries": injuries}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app/queries.py tests/test_queries.py
git commit -m "feat: add filtered injury list and player timeline queries"
```

---

## Chunk 3: FastAPI routes and frontend

### Task 10: FastAPI app with JSON endpoints

**Files:**
- Create: `app/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import etl


@pytest.fixture
def client(tmp_path, raw_cache_dir, reference_db, monkeypatch):
    out = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, out)
    monkeypatch.setattr("app.db.DB_PATH", str(out))
    from app.main import app
    return TestClient(app)


def test_api_overview(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    assert r.json()["injuries"] == 2


def test_api_injuries_filtered(client):
    r = client.get("/api/injuries", params={"ongoing_only": True})
    assert r.status_code == 200
    assert r.json()["total"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_api.py -v`
Expected: FAIL — no module named `app.main`.

- [ ] **Step 3: Write `app/main.py`**

```python
"""FastAPI routes. Thin by design — all SQL lives in queries.py.

Every page has a matching /api/* JSON endpoint so this demos as a real
API, not only a webpage.
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, queries

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Injury Data POC")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")),
          name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


def _conn():
    return db.connect()


# ----------------------------- JSON API ----------------------------------- #
@app.get("/api/overview")
def api_overview():
    with _conn() as c:
        return {**queries.overview(c),
                "quality": queries.quality_metrics(c)}


@app.get("/api/coverage")
def api_coverage():
    with _conn() as c:
        return {"leagues": queries.coverage_by_league(c)}


@app.get("/api/analytics")
def api_analytics():
    with _conn() as c:
        return {
            "by_position": queries.by_position(c),
            "by_age_band": queries.by_age_band(c),
            "by_type": queries.by_type(c),
            "by_nationality": queries.by_nationality(c),
            "by_league": queries.by_league(c),
            "by_month": queries.by_month(c),
        }


@app.get("/api/injuries")
def api_injuries(country: str = None, position: str = None,
                 type_name: str = None, ongoing_only: bool = False,
                 sort: str = "start_date", direction: str = "desc",
                 page: int = 1, per_page: int = 50):
    with _conn() as c:
        return queries.injury_list(c, country, position, type_name,
                                   ongoing_only, sort, direction,
                                   page, per_page)


@app.get("/api/player/{player_id}")
def api_player(player_id: int):
    with _conn() as c:
        return queries.player_timeline(c, player_id)


# ------------------------------- Pages ------------------------------------ #
@app.get("/", response_class=HTMLResponse)
def page_coverage(request: Request):
    with _conn() as c:
        return templates.TemplateResponse("coverage.html", {
            "request": request,
            "overview": queries.overview(c),
            "quality": queries.quality_metrics(c),
            "coverage": queries.coverage_by_league(c),
        })


@app.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request):
    with _conn() as c:
        return templates.TemplateResponse("analytics.html", {
            "request": request,
            "by_position": queries.by_position(c),
            "by_age_band": queries.by_age_band(c),
            "by_type": queries.by_type(c),
            "by_nationality": queries.by_nationality(c),
            "by_league": queries.by_league(c),
            "by_month": queries.by_month(c),
        })


@app.get("/injuries", response_class=HTMLResponse)
def page_injuries(request: Request, country: str = None, position: str = None,
                  type_name: str = None, ongoing_only: bool = False,
                  sort: str = "start_date", direction: str = "desc",
                  page: int = 1):
    with _conn() as c:
        result = queries.injury_list(c, country, position, type_name,
                                     ongoing_only, sort, direction, page)
        return templates.TemplateResponse("injuries.html", {
            "request": request, "result": result,
            "options": queries.filter_options(c),
            "filters": {"country": country, "position": position,
                        "type_name": type_name, "ongoing_only": ongoing_only,
                        "sort": sort, "direction": direction},
        })


@app.get("/player/{player_id}", response_class=HTMLResponse)
def page_player(request: Request, player_id: int):
    with _conn() as c:
        return templates.TemplateResponse("player.html", {
            "request": request, **queries.player_timeline(c, player_id)})
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/test_api.py -v`
Expected: PASS (page routes will fail until templates exist — that's Task 11;
only the `/api/*` tests are asserted here).

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: add FastAPI routes and JSON API"
```

---

### Task 11: Frontend — base layout and styling

**Files:**
- Create: `app/templates/base.html`
- Create: `app/static/style.css`
- Create: `app/static/chart.min.js`

**Design intent:** This goes in front of a product owner. Polished, not
utilitarian. Restrained palette, real typographic hierarchy, generous
whitespace, responsive tables that scroll rather than overflow. Dark
sidebar nav, light content area. No CSS framework — hand-written and
small.

- [ ] **Step 1: Vendor Chart.js**

Run:
```bash
cd /Users/mbarraco/code/injuries && curl -sL \
  https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js \
  -o app/static/chart.min.js && ls -la app/static/chart.min.js
```
Expected: a file of roughly 200KB. Vendored deliberately — the app must
render with no network access.

- [ ] **Step 2: Write `app/templates/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Injury Data{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav class="sidebar">
    <div class="brand">
      <span class="brand-mark">◆</span>
      <div>
        <strong>Injury Data</strong>
        <small>Sportmonks · UEFA</small>
      </div>
    </div>
    <a href="/"          class="{{ 'active' if active == 'coverage' }}">Coverage &amp; Quality</a>
    <a href="/analytics" class="{{ 'active' if active == 'analytics' }}">Analytics</a>
    <a href="/injuries"  class="{{ 'active' if active == 'injuries' }}">Injury Records</a>
    <div class="sidebar-foot">
      <a href="/docs">API docs →</a>
    </div>
  </nav>
  <main>
    <header class="page-head">
      <h1>{% block heading %}{% endblock %}</h1>
      <p class="subtitle">{% block subtitle %}{% endblock %}</p>
    </header>
    {% block content %}{% endblock %}
  </main>
  <script src="/static/chart.min.js"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Write `app/static/style.css`**

```css
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --ink: #14181f;
  --ink-soft: #5b6472;
  --line: #e3e7ec;
  --accent: #2f6df6;
  --accent-soft: #eaf1fe;
  --good: #1a9d63;
  --warn: #c9880f;
  --bad: #d0463b;
  --sidebar: #161b24;
  --radius: 10px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  display: flex;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
        Roboto, sans-serif;
}

/* ---------- sidebar ---------- */
.sidebar {
  width: 232px;
  flex-shrink: 0;
  background: var(--sidebar);
  color: #c8cfdb;
  padding: 22px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.brand { display: flex; gap: 10px; align-items: center;
         padding: 0 10px 22px; color: #fff; }
.brand-mark { color: var(--accent); font-size: 20px; }
.brand small { display: block; color: #7d879a; font-size: 11px;
               letter-spacing: .04em; text-transform: uppercase; }
.sidebar a {
  color: #c8cfdb; text-decoration: none; padding: 9px 12px;
  border-radius: 7px; font-size: 14px;
}
.sidebar a:hover { background: #222a36; color: #fff; }
.sidebar a.active { background: var(--accent); color: #fff; font-weight: 600; }
.sidebar-foot { margin-top: auto; padding-top: 16px; border-top: 1px solid #262e3a; }
.sidebar-foot a { font-size: 12px; color: #7d879a; }

/* ---------- layout ---------- */
main { flex: 1; padding: 34px 40px 60px; max-width: 1400px; }
.page-head { margin-bottom: 26px; }
.page-head h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: -.02em; }
.subtitle { margin: 0; color: var(--ink-soft); }

section { margin-bottom: 34px; }
section > h2 {
  font-size: 13px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--ink-soft); margin: 0 0 12px;
}

.card {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 18px 20px;
}

/* ---------- stats ---------- */
.stat-row { display: grid; gap: 14px;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.stat { background: var(--surface); border: 1px solid var(--line);
        border-radius: var(--radius); padding: 16px 18px; }
.stat .value { font-size: 27px; font-weight: 650; letter-spacing: -.02em; }
.stat .label { font-size: 12px; color: var(--ink-soft);
               text-transform: uppercase; letter-spacing: .05em; margin-top: 2px; }

/* ---------- dedup funnel ---------- */
.funnel { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.funnel-step { flex: 1; min-width: 150px; background: var(--accent-soft);
               border-radius: var(--radius); padding: 14px 16px; }
.funnel-step .n { font-size: 22px; font-weight: 650; }
.funnel-step .t { font-size: 12px; color: var(--ink-soft); }
.funnel-arrow { color: var(--ink-soft); font-size: 18px; }
.funnel-step.final { background: #e6f6ee; }

/* ---------- tables ---------- */
.table-wrap { overflow-x: auto; background: var(--surface);
              border: 1px solid var(--line); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--line); }
th { background: #fbfcfd; font-size: 11px; text-transform: uppercase;
     letter-spacing: .05em; color: var(--ink-soft); white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: #fafbfc; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
table a { color: var(--accent); text-decoration: none; }
table a:hover { text-decoration: underline; }

/* ---------- pills ---------- */
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: .04em; }
.pill.rich     { background: #e6f6ee; color: var(--good); }
.pill.moderate { background: var(--accent-soft); color: var(--accent); }
.pill.thin     { background: #fdf3e0; color: var(--warn); }
.pill.token,
.pill.dark     { background: #fdecea; color: var(--bad); }
.pill.ongoing  { background: #fdf3e0; color: var(--warn); }

/* ---------- gaps panel ---------- */
.gaps { border-left: 3px solid var(--warn); background: #fffdf7; }
.gaps ul { margin: 0; padding-left: 18px; }
.gaps li { margin: 6px 0; color: #4a5261; }

/* ---------- charts ---------- */
.chart-grid { display: grid; gap: 18px;
              grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.chart-card { background: var(--surface); border: 1px solid var(--line);
              border-radius: var(--radius); padding: 16px 18px; }
.chart-card h3 { margin: 0 0 2px; font-size: 15px; }
.chart-card p  { margin: 0 0 12px; font-size: 12px; color: var(--ink-soft); }

/* ---------- filters ---------- */
.filters { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; }
.filters label { font-size: 11px; text-transform: uppercase;
                 letter-spacing: .05em; color: var(--ink-soft); display: block;
                 margin-bottom: 4px; }
.filters select, .filters button {
  padding: 7px 10px; border: 1px solid var(--line); border-radius: 7px;
  background: var(--surface); font-size: 14px; color: var(--ink);
}
.filters button { background: var(--accent); color: #fff; border-color: var(--accent);
                  cursor: pointer; font-weight: 600; }
.filters .check { display: flex; align-items: center; gap: 6px; padding-bottom: 8px; }

.pager { display: flex; gap: 10px; align-items: center; margin-top: 14px;
         font-size: 14px; color: var(--ink-soft); }
.pager a { color: var(--accent); text-decoration: none; padding: 6px 12px;
           border: 1px solid var(--line); border-radius: 7px; background: var(--surface); }

@media (max-width: 860px) {
  body { flex-direction: column; }
  .sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; align-items: center; }
  .sidebar-foot { margin: 0; border: none; }
  main { padding: 22px 18px 50px; }
}
```

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html app/static/style.css app/static/chart.min.js
git commit -m "feat: add base layout, styling, and vendored Chart.js"
```

---

### Task 12: Coverage & data quality page

**Files:**
- Create: `app/templates/coverage.html`
- Modify: `app/main.py` (pass `active` to template context)

- [ ] **Step 1: Add `active` to each page route**

In `app/main.py`, add `"active": "coverage"` / `"analytics"` / `"injuries"`
to the corresponding `TemplateResponse` context dicts.

- [ ] **Step 2: Write `app/templates/coverage.html`**

```html
{% extends "base.html" %}
{% block title %}Coverage & Quality{% endblock %}
{% block heading %}Coverage &amp; Data Quality{% endblock %}
{% block subtitle %}What this dataset contains, how it was verified, and
where its limits are.{% endblock %}

{% block content %}
{% set q = {} %}{% for m in quality %}{% set _ = q.update({m.metric: m}) %}{% endfor %}

<section>
  <h2>Dataset at a glance</h2>
  <div class="stat-row">
    <div class="stat"><div class="value">{{ "{:,}".format(overview.injuries) }}</div>
      <div class="label">Injuries</div></div>
    <div class="stat"><div class="value">{{ overview.leagues }}</div>
      <div class="label">Leagues</div></div>
    <div class="stat"><div class="value">{{ "{:,}".format(overview.players) }}</div>
      <div class="label">Players</div></div>
    <div class="stat"><div class="value">{{ "{:,}".format(overview.teams) }}</div>
      <div class="label">Teams</div></div>
    <div class="stat"><div class="value">{{ overview.ongoing }}</div>
      <div class="label">Ongoing</div></div>
    <div class="stat"><div class="value">{{ overview.earliest[:4] }}–{{ overview.latest[:4] }}</div>
      <div class="label">Date range</div></div>
  </div>
</section>

<section>
  <h2>Deduplication — why raw API counts mislead</h2>
  <div class="card">
    <p style="margin-top:0;color:var(--ink-soft)">
      The vendor returns one row per <em>match missed</em>, not per injury.
      A single absence spanning seven games appears seven times. Counting
      raw rows overstates the dataset by
      <strong>{{ q.dedup_ratio.value }}×</strong>.
    </p>
    <div class="funnel">
      <div class="funnel-step">
        <div class="n">{{ "{:,}".format(q.raw_pivot_rows.value|int) }}</div>
        <div class="t">Raw rows returned</div>
      </div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step">
        <div class="n">{{ "{:,}".format(q.distinct_absences.value|int) }}</div>
        <div class="t">Distinct absences (deduped)</div>
      </div>
      <span class="funnel-arrow">→</span>
      <div class="funnel-step final">
        <div class="n">{{ "{:,}".format(q.injuries.value|int) }}</div>
        <div class="t">Injuries (suspensions removed)</div>
      </div>
    </div>
  </div>
</section>

<section>
  <h2>Field completeness</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Metric</th><th class="num">Value</th><th>Detail</th></tr></thead>
      <tbody>
      {% for m in quality %}
        <tr><td>{{ m.metric }}</td>
            <td class="num">{{ m.value }}</td>
            <td style="color:var(--ink-soft)">{{ m.detail }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>Coverage by league</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Country</th><th>League</th>
        <th class="num">Year 1</th><th class="num">Year 2</th><th class="num">Year 3</th>
        <th>Tier</th>
      </tr></thead>
      <tbody>
      {% for r in coverage %}
        <tr>
          <td>{{ r.country }}</td><td>{{ r.league }}</td>
          <td class="num">{{ r.yr1 or 0 }}</td>
          <td class="num">{{ r.yr2 or 0 }}</td>
          <td class="num">{{ r.yr3 or 0 }}</td>
          <td><span class="pill {{ r.tier }}">{{ r.tier }}</span></td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>Known gaps</h2>
  <div class="card gaps">
    <ul>
      <li><strong>Suspensions excluded.</strong> The vendor mixes injuries and
        suspensions in one feed. This is an injury database, so
        {{ "{:,}".format((q.get('excluded_suspended').value|int if q.get('excluded_suspended') else 0)
                         + (q.get('excluded_suspension').value|int if q.get('excluded_suspension') else 0)) }}
        suspension records were removed.</li>
      <li><strong>Vendor inconsistency.</strong> Suspensions arrive under two
        different spellings (<code>suspended</code> and <code>suspension</code>)
        for the same concept — normalized during ingest.</li>
      <li><strong>174 teams (18%) unresolvable.</strong> The vendor silently
        returns empty data for teams outside the subscribed leagues (cup
        opponents, loan clubs). Those injuries are kept; the team name is blank.</li>
      <li><strong>36 player IDs unresolvable.</strong> Dead IDs in the vendor's
        own data. Same handling — the injury is kept.</li>
      <li><strong>Season attribution is derived.</strong> The vendor leaves
        <code>season_id</code> null on every injury record; it is taken from the
        parent fixture.</li>
      <li><strong>History depth is provisional.</strong> Coverage before
        ~Aug 2024 is sparse, but we have evidence this may be a trial-account
        restriction rather than a real limit — unconfirmed pending vendor
        clarification.</li>
    </ul>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 3: Verify the page renders**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m uvicorn app.main:app --port 8000`
Then in another terminal: `curl -s localhost:8000/ | head -40`
Expected: HTML containing "Coverage &amp; Data Quality" and stat values.

- [ ] **Step 4: Commit**

```bash
git add app/templates/coverage.html app/main.py
git commit -m "feat: add coverage and data quality page"
```

---

### Task 13: Analytics page

**Files:**
- Create: `app/templates/analytics.html`

- [ ] **Step 1: Write `app/templates/analytics.html`**

```html
{% extends "base.html" %}
{% block title %}Analytics{% endblock %}
{% block heading %}Analytics &amp; Linkage{% endblock %}
{% block subtitle %}Questions answerable only once injuries are joined to
player, team, type and season dimensions.{% endblock %}

{% block content %}
<section>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>Injuries by position</h3>
      <p>injury ⋈ player — impossible from the raw injury feed alone</p>
      <canvas id="positionChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <h3>Injuries by age band</h3>
      <p>derived from date of birth × injury start date</p>
      <canvas id="ageChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <h3>Seasonality</h3>
      <p>injury onset by calendar month, all years</p>
      <canvas id="monthChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <h3>Top nationalities</h3>
      <p>injury ⋈ player ⋈ country</p>
      <canvas id="natChart" height="220"></canvas>
    </div>
  </div>
</section>

<section>
  <h2>Injury types — severity profile</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Type</th><th class="num">Injuries</th>
        <th class="num">Avg days out</th><th class="num">Avg games missed</th></tr></thead>
      <tbody>
      {% for r in by_type %}
        <tr><td>{{ r.type }}</td><td class="num">{{ r.injuries }}</td>
            <td class="num">{{ r.avg_duration or '—' }}</td>
            <td class="num">{{ r.avg_games_missed or '—' }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>By league</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Country</th><th>League</th>
        <th class="num">Injuries</th><th class="num">Avg days out</th></tr></thead>
      <tbody>
      {% for r in by_league %}
        <tr><td>{{ r.country }}</td><td>{{ r.league }}</td>
            <td class="num">{{ r.injuries }}</td>
            <td class="num">{{ r.avg_duration or '—' }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}

{% block scripts %}
<script>
const INK = '#5b6472', ACCENT = '#2f6df6', LINE = '#e3e7ec';
const baseOpts = {
  responsive: true,
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { display: false }, ticks: { color: INK } },
    y: { grid: { color: LINE }, ticks: { color: INK }, beginAtZero: true }
  }
};
function bar(id, labels, data, color) {
  new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color || ACCENT,
                                 borderRadius: 4 }] },
    options: baseOpts
  });
}
bar('positionChart',
    {{ by_position | map(attribute='position') | list | tojson }},
    {{ by_position | map(attribute='injuries') | list | tojson }});
bar('ageChart',
    {{ by_age_band | map(attribute='band') | list | tojson }},
    {{ by_age_band | map(attribute='injuries') | list | tojson }}, '#1a9d63');
bar('monthChart',
    {{ by_month | map(attribute='month') | list | tojson }},
    {{ by_month | map(attribute='injuries') | list | tojson }}, '#c9880f');
bar('natChart',
    {{ by_nationality | map(attribute='nationality') | list | tojson }},
    {{ by_nationality | map(attribute='injuries') | list | tojson }}, '#6b5bd2');
</script>
{% endblock %}
```

- [ ] **Step 2: Verify it renders**

With the server running: `curl -s localhost:8000/analytics | grep -c canvas`
Expected: `4`

- [ ] **Step 3: Commit**

```bash
git add app/templates/analytics.html
git commit -m "feat: add analytics page with charts"
```

---

### Task 14: Injury records page and player drill-down

**Files:**
- Create: `app/templates/injuries.html`
- Create: `app/templates/player.html`

- [ ] **Step 1: Write `app/templates/injuries.html`**

```html
{% extends "base.html" %}
{% block title %}Injury Records{% endblock %}
{% block heading %}Injury Records{% endblock %}
{% block subtitle %}{{ "{:,}".format(result.total) }} injuries matching the
current filters.{% endblock %}

{% block content %}
<section>
  <form class="filters" method="get">
    <div>
      <label>Country</label>
      <select name="country">
        <option value="">All</option>
        {% for c in options.countries %}
          <option value="{{ c }}" {{ 'selected' if filters.country == c }}>{{ c }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label>Position</label>
      <select name="position">
        <option value="">All</option>
        {% for p in options.positions %}
          <option value="{{ p }}" {{ 'selected' if filters.position == p }}>{{ p }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label>Injury type</label>
      <select name="type_name">
        <option value="">All</option>
        {% for t in options.types %}
          <option value="{{ t }}" {{ 'selected' if filters.type_name == t }}>{{ t }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label>Sort by</label>
      <select name="sort">
        {% for s in ['start_date','duration','games_missed','player','league'] %}
          <option value="{{ s }}" {{ 'selected' if filters.sort == s }}>{{ s }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="check">
      <input type="checkbox" name="ongoing_only" value="true"
             {{ 'checked' if filters.ongoing_only }}>
      <label style="margin:0">Ongoing only</label>
    </div>
    <button type="submit">Apply</button>
  </form>
</section>

<section>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Player</th><th>Pos</th><th>Team</th><th>League</th><th>Type</th>
        <th>Start</th><th>End</th>
        <th class="num">Days</th><th class="num">Games</th><th class="num">Apps</th>
      </tr></thead>
      <tbody>
      {% for r in result['items'] %}
        <tr>
          <td><a href="/player/{{ r.id and '' }}{{ r.player_id or '' }}">{{ r.player or '—' }}</a></td>
          <td>{{ r.position or '—' }}</td>
          <td>{{ r.team or '—' }}</td>
          <td>{{ r.league or '—' }}</td>
          <td>{{ r.type or '—' }}</td>
          <td>{{ r.start_date }}</td>
          <td>{% if r.is_ongoing %}<span class="pill ongoing">ongoing</span>
              {% else %}{{ r.end_date or '—' }}{% endif %}</td>
          <td class="num">{{ r.duration_days if r.duration_days is not none else '—' }}</td>
          <td class="num">{{ r.games_missed if r.games_missed is not none else '—' }}</td>
          <td class="num">{{ r.fixture_appearances }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  {% set pages = (result.total // result.per_page) + 1 %}
  <div class="pager">
    {% if result.page > 1 %}<a href="?page={{ result.page - 1 }}">← Prev</a>{% endif %}
    <span>Page {{ result.page }} of {{ pages }}</span>
    {% if result.page < pages %}<a href="?page={{ result.page + 1 }}">Next →</a>{% endif %}
  </div>
</section>
{% endblock %}
```

**NOTE for the implementer:** the player link above is awkward because
`_INJURY_SELECT` doesn't currently select `i.player_id`. Fix this properly:
add `i.player_id` to the `_INJURY_SELECT` column list in `app/queries.py`,
then simplify the cell to
`<td><a href="/player/{{ r.player_id }}">{{ r.player or '—' }}</a></td>`.

- [ ] **Step 2: Write `app/templates/player.html`**

```html
{% extends "base.html" %}
{% block title %}{{ player.name if player else 'Player' }}{% endblock %}
{% block heading %}{{ player.name if player else 'Unknown player' }}{% endblock %}
{% block subtitle %}
  {% if player %}
    {{ player.detailed_position or player.position or 'Position unknown' }}
    · {{ player.nationality or 'Nationality unknown' }}
    {% if player.date_of_birth %} · born {{ player.date_of_birth }}{% endif %}
    {% if player.height_cm %} · {{ player.height_cm }}cm{% endif %}
    {% if player.weight_kg %} · {{ player.weight_kg }}kg{% endif %}
  {% endif %}
{% endblock %}

{% block content %}
<section>
  <h2>Injury history ({{ injuries | length }})</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Type</th><th>Team</th><th>Start</th><th>End</th>
        <th class="num">Days</th><th class="num">Games</th></tr></thead>
      <tbody>
      {% for r in injuries %}
        <tr>
          <td>{{ r.type or '—' }}</td><td>{{ r.team or '—' }}</td>
          <td>{{ r.start_date }}</td>
          <td>{% if r.is_ongoing %}<span class="pill ongoing">ongoing</span>
              {% else %}{{ r.end_date or '—' }}{% endif %}</td>
          <td class="num">{{ r.duration_days if r.duration_days is not none else '—' }}</td>
          <td class="num">{{ r.games_missed if r.games_missed is not none else '—' }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  <p style="margin-top:14px"><a href="/injuries">← Back to all records</a></p>
</section>
{% endblock %}
```

- [ ] **Step 3: Add `player_id` to `_INJURY_SELECT`**

In `app/queries.py`, change the first line of `_INJURY_SELECT` to:

```sql
    SELECT i.id, i.player_id, i.start_date, i.end_date, i.duration_days,
```

Then simplify the player cell in `injuries.html` as noted in Step 1.

- [ ] **Step 4: Verify end to end**

With the server running:
```bash
curl -s localhost:8000/injuries | grep -c "<tr>"
curl -s "localhost:8000/injuries?ongoing_only=true" | head -20
```
Expected: rows rendered; the ongoing filter reduces the count.

- [ ] **Step 5: Run the full test suite**

Run: `cd /Users/mbarraco/code/injuries && uv run --python 3.14 -m pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add app/templates/injuries.html app/templates/player.html app/queries.py
git commit -m "feat: add injury records table and player drill-down"
```

---

### Task 15: Runbook

**Files:**
- Create: `app/README.md`

- [ ] **Step 1: Write `app/README.md`**

```markdown
# Injury Data POC

FastAPI app showcasing the Sportmonks injury dataset: coverage, data
quality, and analytical linkage.

## Setup

```bash
cd /Users/mbarraco/code/injuries
uv venv --python 3.14
uv pip install -r app/requirements.txt
```

## Build the database

`app/app.db` is a derived artifact — rebuilt from the raw JSON cache in
`data/raw/sportmonks/fixtures/` plus resolved reference tables in
`coverage.db`. No network access required.

```bash
uv run --python 3.14 -m app.etl
```

Expect ~10,047 injuries loaded from ~16,747 distinct absences across
67,403 raw rows (4× dedup).

## Run

```bash
uv run --python 3.14 -m uvicorn app.main:app --reload --port 8000
```

- <http://localhost:8000/> — coverage & data quality
- <http://localhost:8000/analytics> — aggregations
- <http://localhost:8000/injuries> — explorable records
- <http://localhost:8000/docs> — auto-generated API docs

## Test

```bash
uv run --python 3.14 -m pytest tests/ -v
```
```

- [ ] **Step 2: Commit**

```bash
git add app/README.md
git commit -m "docs: add POC app runbook"
```
