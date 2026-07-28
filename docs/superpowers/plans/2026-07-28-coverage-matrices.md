# Coverage Matrices Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-tabulation grids showing how much data the dataset holds across season × league, season × club and season × player — and, as a prerequisite, repair the league/season dimensions that currently orphan 42% of absences.

**Architecture:** The ETL widens its league and season dimensions from the cached `seasons/*.json` files (mirroring the existing `collect_types`), and gains a `fixture_coverage` aggregate built during the scan it already performs. A new `app/matrix.py` holds one literal SQL statement per measure × row-dimension, pivoted in Python; one Jinja macro renders every grid.

**Tech Stack:** FastAPI, Jinja2, SQLite (read-only at request time), pytest.

**Spec:** [2026-07-28-coverage-matrices-design.md](../specs/2026-07-28-coverage-matrices-design.md)

---

## Slicing — stop safely after any slice

Ordered by value. **Each slice ends with a working, committed app.**

| Slice | Delivers | Cost | Stop here? |
|---|---|---|---|
| **A. Dimension repair** | Leagues 53→62, seasons 159→~255, 11,118 orphaned absences resolved | Medium | **Yes — ship this alone.** It fixes a live bug: the app reports 53 competitions while holding 62 |
| **B. Fixture aggregate** | `fixture_coverage` table populated during the existing scan | Small | Yes — data available, nothing renders it yet |
| **C. Matrix queries** | `app/matrix.py` + tests, no UI | Medium | Yes — verifiable via tests |
| **D. Grid UI** | `/admin` routes, matrix macro, drill-downs | Medium | Yes — the feature |

**Slice A is independently valuable and should ship even if B–D never do.**

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `app/matrix.py` | Measure registry + pivot; one literal SQL per measure × dimension |
| `app/templates/admin/index.html` | What the matrices show, and the framing |
| `app/templates/admin/matrix.html` | A single grid page, any measure or scope |
| `tests/test_dimensions.py` | Slice A: league/season repair |
| `tests/test_matrix.py` | Slices B–C: aggregates and pivots |

**Modified:** `app/etl.py` (dimension loading, fixture aggregate), `app/schema.sql` (season dates, `fixture_coverage`), `app/main.py` (routes), `app/templates/macros.html` (matrix macro), `app/static/style.css` (heat cells), `tests/conftest.py` (seasons cache fixture).

---

## Chunk 1: Slice A — Dimension repair

### Task 1: Season table carries its date window

**Files:** Modify `app/schema.sql`; Test `tests/test_dimensions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dimensions.py
import sqlite3

from app import etl


def test_season_stores_its_date_window(tmp_path, raw_cache_dir, reference_db, seasons_dir):
    """Transfers have no season_id, only a date. Bucketing them needs real
    season windows — every cached season carries starting_at/ending_at, so the
    dimension keeps them rather than guessing at league calendars."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output, seasons_dir=seasons_dir)
    connection = sqlite3.connect(output)

    row = connection.execute(
        "SELECT starting_at, ending_at FROM season WHERE id = 23619").fetchone()
    assert row == ("2024-07-09", "2025-05-31")   # the real window for this season
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest tests/test_dimensions.py -v`
Expected: FAIL — `no such column: starting_at` (and no `seasons_dir` fixture yet)

- [ ] **Step 3: Add the columns**

In `app/schema.sql`, extend the `season` table:

```sql
CREATE TABLE season (
    id INTEGER PRIMARY KEY,
    league_id INTEGER REFERENCES league(id),
    name TEXT,
    is_current INTEGER,
    -- Real window from the vendor, used to bucket transfers (which carry a
    -- date but no season_id) instead of assuming a league calendar.
    starting_at TEXT,
    ending_at TEXT
);
```

- [ ] **Step 4: Add the `seasons_dir` fixture**

In `tests/conftest.py`, mirroring `players_dir`:

```python
@pytest.fixture
def seasons_dir(tmp_path):
    """Cached league+seasons files, the wider source for both dimensions.

    Includes a competition ABSENT from reference_db (league 2, a cup) — that is
    the gap the repair exists to close, so without it the test would pass
    against the broken build.
    """
    directory = tmp_path / "seasons"
    directory.mkdir()
    (directory / "10.json").write_text(json.dumps({
        # country_id 999 is deliberately fictional: the other fixtures already
        # call this country "Testland", and borrowing a real id (320 is
        # Denmark) would quietly attach a fake name to a real entity.
        "id": 10, "name": "Test League", "country_id": 999,
        "seasons": [
            {"id": 77, "league_id": 10, "name": "2024/2025", "is_current": True,
             "starting_at": "2024-08-16", "ending_at": "2025-05-31"},
            {"id": 78, "league_id": 10, "name": "2023/2024", "is_current": False,
             "starting_at": "2023-08-11", "ending_at": "2024-05-19"},
        ],
    }))
    # A real competition with its real values, so the cup path is exercised
    # against data that matches production rather than invented figures.
    (directory / "2.json").write_text(json.dumps({
        "id": 2, "name": "Champions League", "country_id": 41,
        "seasons": [
            {"id": 23619, "league_id": 2, "name": "2024/2025", "is_current": False,
             "starting_at": "2024-07-09", "ending_at": "2025-05-31"},
        ],
    }))
    return directory


@pytest.fixture
def countries_file(tmp_path):
    path = tmp_path / "countries.json"
    path.write_text(json.dumps([
        {"id": 999, "name": "Testland"},   # fictional, as above
        {"id": 41, "name": "Europe"},      # real: what the cups resolve to
    ]))
    return path
```

- [ ] **Step 5: Implement `collect_leagues_and_seasons` in `app/etl.py`**

```python
DEFAULT_SEASONS_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "seasons")
DEFAULT_COUNTRIES_FILE = os.path.join(BASE, "data", "raw", "sportmonks", "countries.json")


def collect_leagues_and_seasons(reference, seasons_dir, countries_file):
    """League and season dimensions, widened from the cached seasons files.

    coverage.db only holds what ingest/resolve.py swept, which is the 53
    domestic leagues — so the UEFA cups reached neither dimension and 42% of
    absences resolved to no competition and no season. The cached
    seasons/{league_id}.json files cover all 62 competitions and are already on
    disk; coverage.db remains the fallback so a missing cache degrades to the
    old behaviour rather than losing rows.

    Returns (leagues, seasons) ready for executemany.
    """
    countries = {}
    if countries_file and os.path.exists(countries_file):
        with open(countries_file, encoding="utf-8") as source:
            countries = {int(row["id"]): row.get("name")
                         for row in json.load(source) if row.get("id") is not None}

    leagues, seasons = {}, {}
    # coverage.db first, so cached files win on conflict — they are the wider
    # and more recently fetched source.
    for row in reference.execute(
            "SELECT id, league_id, country, league_name, name, is_current FROM sportmonks_season"):
        if row[1]:
            leagues.setdefault(int(row[1]), (int(row[1]), row[2], row[3]))
        seasons.setdefault(int(row[0]),
                           (int(row[0]), int(row[1]) if row[1] else None, row[4], row[5], None, None))

    for path in sorted(glob.glob(os.path.join(seasons_dir or "", "*.json"))):
        with open(path, encoding="utf-8") as source:
            document = json.load(source)
        league_id = document.get("id")
        if league_id is None:
            continue
        leagues[int(league_id)] = (int(league_id),
                                   countries.get(document.get("country_id")),
                                   document.get("name"))
        for season in document.get("seasons") or []:
            if season.get("id") is None:
                continue
            seasons[int(season["id"])] = (
                int(season["id"]), int(season.get("league_id") or league_id),
                season.get("name"), int(bool(season.get("is_current"))),
                season.get("starting_at"), season.get("ending_at"))

    return sorted(leagues.values()), sorted(seasons.values())
```

- [ ] **Step 6: Wire it into `build()`**

Add `seasons_dir=DEFAULT_SEASONS_DIR, countries_file=DEFAULT_COUNTRIES_FILE` to the signature, and replace the existing league/season inserts:

```python
league_rows, season_rows = collect_leagues_and_seasons(reference, seasons_dir, countries_file)
connection.executemany("INSERT OR IGNORE INTO league VALUES (?, ?, ?)", league_rows)
connection.executemany("INSERT OR IGNORE INTO season VALUES (?, ?, ?, ?, ?, ?)", season_rows)
```

Thread `seasons_dir` and `countries_file` through the `conftest.py` db-building fixtures exactly as `types_file` already is, so tests never read real repo data.

- [ ] **Step 7: Run, expect pass**

Run: `uv run pytest tests/test_dimensions.py -v`

- [ ] **Step 8: Commit**

```bash
git add app/schema.sql app/etl.py tests/conftest.py tests/test_dimensions.py
git commit -m "fix: build league and season dimensions from the full cached taxonomy"
```

---

### Task 2: Prove the orphans are gone

**Files:** Test `tests/test_dimensions.py`

- [ ] **Step 1: Write the test that would have caught the bug**

```python
def test_cup_competitions_reach_the_league_dimension(tmp_path, raw_cache_dir,
                                                     reference_db, seasons_dir, countries_file):
    """coverage.db knows only the domestic leagues it swept. League 2 exists
    solely in the cached seasons files, so this fails against the old build."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    assert connection.execute(
        "SELECT country, name FROM league WHERE id = 2").fetchone() == ("Europe", "Champions League")


def test_no_absence_is_orphaned_from_its_competition(tmp_path, raw_cache_dir,
                                                     reference_db, seasons_dir, countries_file):
    """42% of real absences pointed at a league_id absent from the dimension,
    so they showed a blank competition and would vanish from a coverage grid."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    orphans = connection.execute("""
        SELECT COUNT(*) FROM absence a
        LEFT JOIN league l ON l.id = a.league_id WHERE l.id IS NULL""").fetchone()[0]
    assert orphans == 0
```

- [ ] **Step 2: Run, then rebuild the real database**

```bash
uv run pytest tests/ -q
uv run python -m app.etl
```

- [ ] **Step 3: Verify the repair on real data**

```bash
uv run sqlite3 app/app.db "SELECT COUNT(*) FROM league;"          # expect 62, was 53
uv run sqlite3 app/app.db "SELECT COUNT(*) FROM season;"          # expect ~255, was 159
uv run sqlite3 app/app.db "SELECT COUNT(*) FROM absence a LEFT JOIN league l ON l.id=a.league_id WHERE l.id IS NULL;"
```

Expected: 62, ~255, and **0** orphans (was 11,118).

> **Tell the user when this ships.** The dashboard's competition count changes
> 53 → 62 and previously blank competition cells populate. That is a
> correction, but it looks like the data changed.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: guard the league and season dimension repair"
```

---

## Chunk 2: Slices B & C — Aggregate and queries

### Task 3: `fixture_coverage` table

**Files:** Modify `app/schema.sql`, `app/etl.py`; Test `tests/test_matrix.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fixture_coverage_counts_cached_fixtures(tmp_path, raw_cache_dir,
                                                 reference_db, seasons_dir, countries_file):
    """Fixtures exist only in the raw cache, never in app.db. The grid needs
    them aggregated during the scan collect_absences already performs."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    # raw_cache_dir holds one league-10 file with 2 fixtures, both season 77.
    assert connection.execute(
        "SELECT fixtures, non_empty_months FROM fixture_coverage "
        "WHERE league_id = 10 AND season_id = 77").fetchone() == (2, 1)
```

- [ ] **Step 2: Run, expect failure** (`no such table: fixture_coverage`)

- [ ] **Step 3: Add the table**

```sql
-- Fixture counts per league-season. Fixtures live only in the raw cache, so
-- without this the coverage grids cannot show what was actually fetched.
-- Keyed on season_id, not a label: the cache scan runs BEFORE the season
-- dimension is loaded, so labels do not exist yet and are joined at read time.
CREATE TABLE fixture_coverage (
    league_id        INTEGER REFERENCES league(id),
    season_id        INTEGER,
    fixtures         INTEGER NOT NULL,
    non_empty_months INTEGER NOT NULL,
    PRIMARY KEY (league_id, season_id)
);
```

`season_id` is deliberately **not** a foreign key: some cached fixtures
reference seasons outside the dimension, and dropping them would understate
coverage — the one error these tables must not make.

- [ ] **Step 4: Aggregate during the existing scan**

In `collect_absences()`, alongside the per-year counters:

```python
    # (league_id, season_id) -> [fixtures, months]. Collected here because this
    # loop already opens every cached file; a second pass would double the I/O
    # for counts we can get for free.
    fixture_coverage = {}
```

Inside the per-file loop, after loading `document`:

```python
        league_id = document.get("league_id")
        months_seen = set()
        for fixture in document.get("fixtures", []):
            key = (league_id, fixture.get("season_id"))
            entry = fixture_coverage.setdefault(key, [0, 0])
            entry[0] += 1
            if key not in months_seen:
                months_seen.add(key)
                entry[1] += 1
```

Return it alongside the existing values and insert in `build()`.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/test_matrix.py -v
git add -A && git commit -m "feat: aggregate fixture counts per league-season during the ETL scan"
```

---

### Task 4: `app/matrix.py` — measures and pivot

**Files:** Create `app/matrix.py`; Test `tests/test_matrix.py`

- [ ] **Step 1: Write the failing tests**

```python
from app import matrix


def test_pivots_counts_into_season_columns(connection):
    result = matrix.build(connection, "absences", scope="league")

    league = next(row for row in result["rows"] if row["id"] == 10)
    assert league["cells"]["2024/2025"] == 3
    assert league["total"] == 3


def test_empty_and_zero_are_different(connection):
    """A cell we hold nothing for must not look like a cell that recorded
    nothing — that distinction is the entire point of a coverage view."""
    result = matrix.build(connection, "absences", scope="league")
    league = next(row for row in result["rows"] if row["id"] == 10)

    assert "2023/2024" not in league["cells"]        # absent, not zero


def test_unattributed_column_retains_unresolvable_records(connection):
    """Records whose season cannot be resolved are counted, not dropped:
    omitting them would overstate how complete the dataset is."""
    result = matrix.build(connection, "absences", scope="league")

    assert "unattributed" in result
```

- [ ] **Step 2: Run, expect failure** (`No module named 'app.matrix'`)

- [ ] **Step 3: Implement**

```python
"""Cross-tabulations of what the dataset holds, by season.

Deliberately NOT a generic cross-tab engine. Each measure declares complete SQL
per row dimension — twelve literal statements rather than assembled ones. A
generic version would interpolate identifiers against a whitelist and return an
untyped shape, which is harder to read and test for four measures and three
dimensions.

These grids answer "how much data do we hold", never "were there more injuries
that year". Sidelined coverage climbs from 0.00 records per fixture pre-2006 to
~4 today, so a season comparison measures the vendor's backfill; read as
coverage, that same variation is the finding.
"""
from dataclasses import dataclass

from app.db import rows


@dataclass(frozen=True)
class Measure:
    label: str
    by_league: str
    by_club: str
    by_player: str


MEASURES = {
    "absences": Measure(
        label="Absences",
        by_league="""
            SELECT league.id AS row_id, league.name AS row_label,
                   season.name AS season, COUNT(*) AS value
            FROM absence
            JOIN league ON league.id = absence.league_id
            LEFT JOIN season ON season.id = absence.season_id
            GROUP BY league.id, league.name, season.name
        """,
        by_club="...",   # same shape, JOIN team, WHERE absence.league_id = ?
        by_player="...",  # same shape, JOIN player, WHERE absence.team_id = ?
    ),
    # transfers / minutes / fixtures follow the same shape.
}


def build(connection, measure, scope="league", scope_id=None):
    """Pivot one measure into {rows, seasons, unattributed}.

    Pivoting happens here rather than in SQL: the season axis grows as cup
    seasons are restored (6 labels domestically, 37 including cups), and a SQL
    pivot would hardcode the columns.
    """
    ...
```

- [ ] **Step 4: Run, then commit**

```bash
uv run pytest tests/test_matrix.py -v
git add app/matrix.py tests/test_matrix.py
git commit -m "feat: coverage matrix queries with season pivot"
```

---

## Chunk 3: Slice D — Grid UI

### Task 5: The matrix macro

**Files:** Modify `app/templates/macros.html`, `app/static/style.css`

- [ ] **Step 1: Add the macro**

```jinja
{# One grid, any measure or scope. Heat intensity is scaled to the largest
   value in the grid so rows stay comparable with each other.
   Empty renders blank, zero renders "0" — different claims. #}
{% macro matrix(data, drill_kind=None) %}
<div class="table-wrap"><table class="matrix">
  <thead><tr><th>{{ data.row_label }}</th>
    {% for season in data.seasons %}<th class="num">{{ season }}</th>{% endfor %}
    {% if data.unattributed %}<th class="num" title="Records whose season could not be resolved">unattributed</th>{% endif %}
    <th class="num">Total</th></tr></thead>
  <tbody>
  {% for row in data.rows %}<tr>
    <td>{% if drill_kind %}<a href="/admin/matrix/{{ data.measure }}/{{ drill_kind }}/{{ row.id }}">{{ row.label }}</a>{% else %}{{ row.label }}{% endif %}</td>
    {% for season in data.seasons %}
      {% set value = row.cells.get(season) %}
      <td class="num heat" style="--heat: {{ (value / data.max) if value and data.max else 0 }}">{{ value if value is not none else '' }}</td>
    {% endfor %}
    {% if data.unattributed %}<td class="num">{{ row.unattributed or '' }}</td>{% endif %}
    <td class="num total">{{ '{:,}'.format(row.total) }}</td>
  </tr>{% endfor %}
  </tbody>
</table></div>
{% endmacro %}
```

- [ ] **Step 2: Style the heat cells**

```css
.matrix .heat { background: color-mix(in srgb, var(--accent) calc(var(--heat) * 55%), transparent); }
.matrix td.total { font-weight: 600; }
.matrix th:first-child, .matrix td:first-child { position: sticky; left: 0; background: var(--surface); }
```

- [ ] **Step 3: Commit**

---

### Task 6: Routes and pages

**Files:** Modify `app/main.py`; Create `app/templates/admin/{index,matrix}.html`; Test `tests/test_matrix.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_admin_index_lists_every_measure(client):
    body = client.get("/admin").text
    for measure in ("absences", "transfers", "minutes", "fixtures"):
        assert f"/admin/matrix/{measure}" in body


def test_matrix_page_renders_a_grid(client):
    response = client.get("/admin/matrix/absences")
    assert response.status_code == 200
    assert "2024/2025" in response.text


def test_unknown_measure_is_404(client):
    assert client.get("/admin/matrix/nonsense").status_code == 404


def test_league_rows_drill_into_clubs(client):
    assert 'href="/admin/matrix/absences/league/10"' in client.get("/admin/matrix/absences").text
```

- [ ] **Step 2: Add routes**

```python
@app.get("/admin", response_class=HTMLResponse)
def page_admin(request: Request, _: str = Depends(verify_auth)):
    return templates.TemplateResponse(request, "admin/index.html",
                                      {"active": "admin", "measures": matrix.MEASURES})


@app.get("/admin/matrix/{measure}", response_class=HTMLResponse)
def page_matrix(request: Request, measure: str, _: str = Depends(verify_auth)):
    if measure not in matrix.MEASURES:
        raise HTTPException(status_code=404, detail="Unknown measure")
    with _connection() as connection:
        data = matrix.build(connection, measure, scope="league")
    return templates.TemplateResponse(request, "admin/matrix.html",
                                      {"active": "admin", "data": data, "drill_kind": "league"})
```

Plus `/admin/matrix/{measure}/league/{id}` and `/admin/matrix/{measure}/team/{id}`, each 404ing on an unknown measure or id. Add an `Admin` link to the sidebar nav in `base.html`.

- [ ] **Step 3: Write the templates**

`admin/index.html` states the framing once, prominently: these tables show what
the dataset contains, not what happened in football, and the reason is the
coverage ramp. Link each measure.

`admin/matrix.html` renders `macros.matrix(data, drill_kind)` with breadcrumbs
and, for transfers, the note that bucketing by date is approximate.

- [ ] **Step 4: Run the suite and commit**

```bash
uv run pytest tests/ -q
git add -A && git commit -m "feat: /admin coverage matrices with drill-down"
```

---

## Final verification

- [ ] `uv run pytest tests/ -q` — green
- [ ] `uv run python -m app.etl` — rebuilds; leagues 62, seasons ~255, 0 orphaned absences
- [ ] Walk `/admin` → a measure → a league → a club, confirming each grid narrows
- [ ] Confirm an empty cell and a `0` cell look different
- [ ] Confirm the dashboard now reports 62 competitions
