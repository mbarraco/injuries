# Injury App Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the injury POC into a navigable product — every entity linked and browsable, minutes-based injury rates surfaced, global search, and a maintainable template/CSS/query structure.

**Architecture:** Server-rendered FastAPI + Jinja, progressively enhanced with vendored htmx so search/filter/paging swap HTML fragments without a reload. One rendering path (Jinja) for both full pages and fragments. `queries.py` splits into a package; templates split into pages/partials with shared macros.

**Tech Stack:** FastAPI, Jinja2, SQLite (read-only), htmx (vendored), Chart.js (already vendored), pytest.

**Spec:** [2026-07-27-injury-app-redesign-design.md](../specs/2026-07-27-injury-app-redesign-design.md)

---

## Slicing — stop safely after any slice

Ordered by value per token. **Each slice ends with a working, committed app**, so
running out of budget mid-plan leaves working software, never a half-migration.
Do not start a slice you can't finish; the risky ones are called out.

| Slice | Delivers | Cost | Stop here? |
|---|---|---|---|
| **A. Safety & speed** | git-lfs, env credentials, indexes | Small | Yes — app unchanged, but secure and faster |
| **B. Linking** | `entity_link` macro + league/team/type pages, existing tables link out | Large | Yes — this is the core of the request |
| **C. Depth** | season pages, player minutes + transfers, category filter | Medium | Yes |
| **D. Visual** | design tokens, dark mode, responsive, readable templates | Large | Yes — purely cosmetic, safe to defer |
| **E. Search** | vendored htmx, global prefix search | Medium | Yes |
| **F. Analysis** | rate metric, dashboard, coverage rewrite, analytics linking | Large | Yes |

**Tasks deliberately dropped from the critical path:**

- **Task 5 (queries package split)** — pure file shuffling: expensive in output
  tokens, zero user-visible value, and leaves broken imports if interrupted. Let
  `queries.py` grow; revisit only when it actually hurts to work in.
- **Task 3 (session login)** — nice UX, but HTTP Basic already works. The
  *security* fix (env credentials, Task 2) is cheap and stays in Slice A; the
  *convenience* fix can wait.

**Within a slice, order matters:** in B and C, create each detail page **before**
adding links pointing at it, so the app never has links to routes that 404.

**Per-slice ritual:** start a fresh session, point it at this plan and the slice,
finish the slice, run `uv run pytest tests/ -q`, commit. Don't carry one slice's
context into the next — the plan file is the context.

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `app/auth.py` | Credential loading, constant-time verify, session + Basic dependencies |
| `app/queries/__init__.py` | Re-exports so `from app import queries` keeps working |
| `app/queries/overview.py` | Dashboard tiles, quality metrics, coverage-by-year |
| `app/queries/absences.py` | Absence list: filters, category, sort, pagination |
| `app/queries/entities.py` | player / team / league / season / type detail |
| `app/queries/analytics.py` | Aggregations (position, age, type, month, league) |
| `app/queries/rates.py` | Injury rate per 1000 minutes + the minutes threshold |
| `app/queries/search.py` | Global prefix search across entities |
| `app/templates/macros.html` | table, pill, stat tile, `entity_link`, breadcrumbs, empty state |
| `app/templates/pages/*.html` | One file per page |
| `app/templates/partials/*.html` | htmx fragments |
| `app/static/htmx.min.js` | Vendored htmx |
| `tests/test_auth.py` | Credential + session behaviour |
| `tests/test_entities.py` | Entity pages render and link correctly |
| `tests/test_rates.py` | Rate metric and threshold |
| `tests/test_search.py` | Search matching |

**Modified:** `app/main.py` (routes), `app/db.py` (unchanged interface), `app/schema.sql` (indexes), `app/README.md`, `.gitignore`, `.gitattributes` (new, for LFS), `tests/test_api.py` (credentials).

**Deleted:** `app/requirements.txt` (empty, superseded by `pyproject.toml`), `app/queries.py` (becomes the package).

---

## Test fixtures (add to `tests/conftest.py` before Chunk 3)

Several tasks below reference fixtures that do not exist yet. Add them first, or
their tests fail for the wrong reason:

```python
@pytest.fixture
def connection(tmp_path, raw_cache_dir, reference_db):
    """A built app.db opened read-only — for testing query functions directly."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    return db.connect(output)


@pytest.fixture
def client_no_session(tmp_path, raw_cache_dir, reference_db, monkeypatch):
    """A client with NO auth headers, for exercising the login redirect path.

    Distinct from `client`, which carries Basic credentials and would never see
    a redirect.
    """
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    monkeypatch.setattr("app.db.DB_PATH", str(output))
    from app.main import app
    return TestClient(app)
```

The existing `reference_db` fixture provides: league `10` ("Test League",
Testland), season `77`, team `100`, type `500`, players `5001` and `5003`. Every
entity-page test below uses those ids.

**Rate tests need player_season rows**, which `reference_db` does not create —
add a `players_dir` with a `statistics` block (see the existing
`test_extracts_player_season_stats` in `tests/test_etl.py` for the shape) and
pass it to `etl.build(..., players_dir=...)`. Include one player above 450
minutes and one below, so the floor is genuinely exercised rather than
vacuously true.

---

## Chunk 1: Infrastructure & Auth

### Task 1: Repo hygiene

**Files:**
- Modify: `.gitignore`
- Create: `.gitattributes`
- Delete: `app/requirements.txt`
- Modify: `app/README.md`

- [ ] **Step 1: Track the database with git-lfs**

```bash
git lfs install
git lfs track "app/app.db"
```

This creates `.gitattributes` containing `app/app.db filter=lfs diff=lfs merge=lfs -text`.

> **Note:** this affects FUTURE commits only. The 14 existing `app.db` blobs stay in history. Purging them needs `git-filter-repo`, which rewrites SHAs — explicitly out of scope per the spec.

- [ ] **Step 2: Ignore macOS cruft and remove the tracked copy**

Add to `.gitignore`:

```
.DS_Store
```

```bash
git rm --cached app/.DS_Store
```

- [ ] **Step 3: Delete the empty requirements file**

```bash
git rm app/requirements.txt
```

- [ ] **Step 4: Fix the README's broken install instructions**

In `app/README.md`, replace `uv pip install -r app/requirements.txt` with `uv sync`. Update the page list to the new routes (dashboard, absences, players, teams, leagues, seasons, types, analytics, coverage).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: track app.db via lfs, drop empty requirements, fix readme"
```

---

### Task 2: Environment-driven credentials

**Files:**
- Create: `app/auth.py`
- Create: `tests/test_auth.py`
- Modify: `app/main.py:17-22`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import pytest
from app import auth


def test_credentials_read_from_environment(monkeypatch):
    monkeypatch.setenv("INJURY_APP_USER", "alice")
    monkeypatch.setenv("INJURY_APP_PASSWORD", "s3cret")
    assert auth.verify("alice", "s3cret") is True


def test_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("INJURY_APP_USER", "alice")
    monkeypatch.setenv("INJURY_APP_PASSWORD", "s3cret")
    assert auth.verify("alice", "wrong") is False


def test_refuses_to_run_without_configured_credentials(monkeypatch):
    """An unset password must fail closed, never authenticate everyone."""
    monkeypatch.delenv("INJURY_APP_USER", raising=False)
    monkeypatch.delenv("INJURY_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="INJURY_APP_USER"):
        auth.verify("alice", "s3cret")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Implement**

```python
# app/auth.py
"""Authentication: env-driven credentials, session for pages, Basic for the API."""
import os
import secrets

USER_VAR, PASSWORD_VAR = "INJURY_APP_USER", "INJURY_APP_PASSWORD"


def _configured():
    """The expected credentials, or a loud failure.

    Fails closed: an unset password must never mean "accept anything", which is
    what a plain os.getenv default would silently produce.
    """
    user, password = os.getenv(USER_VAR), os.getenv(PASSWORD_VAR)
    if not user or not password:
        raise RuntimeError(
            f"{USER_VAR} and {PASSWORD_VAR} must be set — refusing to start unauthenticated")
    return user, password


def verify(username, password):
    """Constant-time credential check.

    compare_digest rather than == so response timing doesn't leak how much of
    the credential was correct.
    """
    expected_user, expected_password = _configured()
    return (secrets.compare_digest(username, expected_user)
            & secrets.compare_digest(password, expected_password))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Point main.py at it and update the API test credentials**

In `app/main.py`, replace the hardcoded comparison in `verify_auth` with `auth.verify(credentials.username, credentials.password)`.

In `tests/test_api.py`, replace the hardcoded header with a fixture that sets the env vars and builds the header from them:

```python
@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("INJURY_APP_USER", "tester")
    monkeypatch.setenv("INJURY_APP_PASSWORD", "testpass")
    return "tester", "testpass"


_AUTH_HEADER = "Basic " + base64.b64encode(b"tester:testpass").decode()
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest tests/ -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/auth.py app/main.py tests/test_auth.py tests/test_api.py
git commit -m "feat: move credentials to environment with constant-time compare"
```

> **Action for the human:** the old password is in git history and must be considered burned. Put a NEW value in `.env` (already gitignored) — do not reuse it.

---

### Task 3: Session login for pages, Basic for the API

**Files:**
- Modify: `app/auth.py`, `app/main.py`
- Create: `app/templates/pages/login.html`
- Modify: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_page_redirects_to_login_when_anonymous(client_no_session):
    response = client_no_session.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_then_page_access(client_no_session):
    client_no_session.post("/login", data={"username": "tester", "password": "testpass"})
    assert client_no_session.get("/").status_code == 200


def test_logout_clears_session(client_no_session):
    client_no_session.post("/login", data={"username": "tester", "password": "testpass"})
    client_no_session.post("/logout")
    assert client_no_session.get("/", follow_redirects=False).status_code == 303


def test_api_still_uses_basic_auth(client):
    """Scripts and curl must keep working without a session."""
    assert client.get("/api/overview").status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — no `/login` route

- [ ] **Step 3: Add session middleware and the dependencies**

In `app/main.py`, after creating `app`:

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(SessionMiddleware, secret_key=auth.session_secret(), same_site="lax")
```

In `app/auth.py`:

```python
SECRET_VAR = "INJURY_APP_SECRET"


def session_secret():
    """Signing key for the session cookie.

    Generated per-process when unset so local dev works, at the cost of
    invalidating sessions on restart — acceptable locally, but set it in
    deployment or every restart logs everyone out.
    """
    return os.getenv(SECRET_VAR) or secrets.token_hex(32)


async def require_session(request: Request):
    """Page guard: redirect to the login form rather than a browser dialog."""
    if not request.session.get("user"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return request.session["user"]
```

- [ ] **Step 4: Add the routes**

```python
@app.get("/login", response_class=HTMLResponse)
def page_login(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "pages/login.html", {"error": error})


@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not auth.verify(username, password):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def do_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
```

Swap every **page** route's dependency from `verify_auth` to `require_session`. Leave every `/api/*` route on `verify_auth` (Basic).

- [ ] **Step 5: Build the login template**

`app/templates/pages/login.html` — a centred card, single form posting to `/login`, showing "Incorrect username or password" when `error` is set. Deliberately does not say which field was wrong.

- [ ] **Step 6: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add app/auth.py app/main.py app/templates/pages/login.html tests/test_auth.py
git commit -m "feat: session login for pages, keep basic auth for api"
```

---

### Task 4: Indexes for the new access paths

**Files:**
- Modify: `app/schema.sql`
- Modify: `tests/test_etl.py`

- [ ] **Step 1: Write the failing test**

```python
def test_creates_indexes_for_entity_pages(tmp_path, raw_cache_dir, reference_db):
    """Team/season/transfer pages filter on columns that were unindexed."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    connection = sqlite3.connect(output)
    names = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_absence_team", "idx_player_season_season", "idx_player_season_team",
            "idx_transfer_from", "idx_transfer_to"} <= names
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_etl.py::test_creates_indexes_for_entity_pages -v`
Expected: FAIL — index names missing

- [ ] **Step 3: Add them to `app/schema.sql`**

```sql
-- Entity detail pages filter on these; without them every team, season and
-- transfer page is a full table scan.
CREATE INDEX idx_absence_team         ON absence(team_id);
CREATE INDEX idx_player_season_season ON player_season(season_id);
CREATE INDEX idx_player_season_team   ON player_season(team_id);
CREATE INDEX idx_transfer_from        ON transfer(from_team_id);
CREATE INDEX idx_transfer_to          ON transfer(to_team_id);
```

- [ ] **Step 4: Run and rebuild**

Run: `uv run pytest tests/test_etl.py -v && uv run python -m app.etl`
Expected: PASS, then a rebuilt database

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql tests/test_etl.py && git commit -m "perf: index columns used by entity pages"
```

---

### Task 5: Split `queries.py` into a package

**Files:**
- Delete: `app/queries.py`
- Create: `app/queries/{__init__,overview,absences,entities,analytics,rates,search}.py`

- [ ] **Step 1: Confirm the current suite is green (this is a refactor — behaviour must not change)**

Run: `uv run pytest tests/ -q`
Expected: all pass. Record the count.

- [ ] **Step 2: Create the package, moving functions verbatim**

- `overview.py` ← `overview`, `quality_metrics`, `coverage_by_league`
- `absences.py` ← `_INJURY_SELECT`, `_SORTABLE`, `injury_list`, `filter_options`
- `entities.py` ← `player_timeline`
- `analytics.py` ← `by_position`, `by_age_band`, `by_type`, `by_nationality`, `by_league`, `by_month`
- `rates.py`, `search.py` — empty for now

`__init__.py` re-exports everything so `from app import queries` and every existing call site keeps working:

```python
"""Query layer, split by concern. Re-exported so callers import one namespace."""
from app.queries.absences import *     # noqa: F401,F403
from app.queries.analytics import *    # noqa: F401,F403
from app.queries.entities import *     # noqa: F401,F403
from app.queries.overview import *     # noqa: F401,F403
```

- [ ] **Step 3: Run the suite — it must pass unchanged**

Run: `uv run pytest tests/ -q`
Expected: identical pass count to Step 1. No test edits allowed in this task; if a test needs changing, the refactor changed behaviour and is wrong.

- [ ] **Step 4: Commit**

```bash
git add -A app/queries* && git commit -m "refactor: split queries into a package by concern"
```

---

## Chunk 2: Presentation Foundation

### Task 6: Design tokens and a real stylesheet

**Files:**
- Modify: `app/static/style.css`

- [ ] **Step 1: Rewrite as a structured stylesheet**

Replace the single minified line with sections: tokens, reset, layout, nav, tables, cards, pills, forms, charts, responsive. Tokens as custom properties on `:root`, with a `prefers-color-scheme: dark` block overriding them.

Requirements:
- Type scale and spacing scale as variables — no hardcoded pixel values in component rules.
- `.table-wrap { overflow-x: auto; }` so wide tables scroll instead of breaking the page.
- Sidebar collapses to a top bar under 768px.
- Focus states visible on every interactive element (keyboard navigation).

- [ ] **Step 2: Verify visually**

Run: `uv run python -m uvicorn app.main:app --reload --port 8000`
Check `/` and `/injuries` in light and dark mode, and at 375px width.

- [ ] **Step 3: Commit**

```bash
git add app/static/style.css && git commit -m "style: design tokens, dark mode, responsive tables"
```

---

### Task 7: Shared macros

**Files:**
- Create: `app/templates/macros.html`
- Modify: `app/templates/base.html`

- [ ] **Step 1: Write the macros**

```jinja
{# entity_link — the single place an entity reference is rendered.
   Centralised because 244 teams and 21 players never resolve to names (cup
   qualifying-round clubs outside the plan), and every call site would
   otherwise invent its own fallback. #}
{% macro entity_link(kind, id, label) %}
  {%- if id and label -%}
    <a href="/{{ kind }}/{{ id }}" class="entity-link">{{ label }}</a>
  {%- elif label -%}
    <span class="entity-unresolved" title="Not in our data">{{ label }}</span>
  {%- else -%}
    <span class="muted">—</span>
  {%- endif -%}
{% endmacro %}

{% macro breadcrumbs(trail) %}
<nav class="breadcrumbs" aria-label="Breadcrumb">
  {% for crumb in trail %}
    {% if crumb.href and not loop.last %}<a href="{{ crumb.href }}">{{ crumb.label }}</a>
    {% else %}<span aria-current="page">{{ crumb.label }}</span>{% endif %}
    {% if not loop.last %}<span class="sep">›</span>{% endif %}
  {% endfor %}
</nav>
{% endmacro %}

{% macro stat(value, label, href=None) %}
<div class="stat">
  {% if href %}<a href="{{ href }}">{% endif %}
  <div class="value">{{ '{:,}'.format(value) if value is number else value }}</div>
  <div class="label">{{ label }}</div>
  {% if href %}</a>{% endif %}
</div>
{% endmacro %}

{% macro empty_state(message) %}
<p class="empty">{{ message }}</p>
{% endmacro %}
```

- [ ] **Step 2: Reformat `base.html`**

Break the one-line body into readable markup. Add: header with global search input (htmx-enabled, targets `#search-results`), breadcrumb slot, and a logout button.

- [ ] **Step 3: Vendor htmx**

Download htmx to `app/static/htmx.min.js` and add `<script src="/static/htmx.min.js"></script>` to `base.html`, matching how `chart.min.js` is already vendored.

- [ ] **Step 4: Verify existing pages still render**

Run: `uv run pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add app/templates/ app/static/htmx.min.js
git commit -m "feat: shared template macros, htmx, readable base layout"
```

---

## Chunk 3: Entity Pages

> Tasks 8–12 share a shape. For each: query function → **index page** → **detail page** → test. Both pages are required — the dashboard test in Task 16 asserts `/players`, `/teams`, `/leagues`, `/seasons` and `/types` all exist, so skipping an index breaks it. The `entity_link` macro from Task 7 is used for every outbound reference.

### Task 8: League pages

**Files:**
- Modify: `app/queries/entities.py`, `app/main.py`
- Create: `app/templates/pages/leagues.html`, `app/templates/pages/league.html`
- Create: `tests/test_entities.py`

- [ ] **Step 1: Write the failing test**

```python
def test_league_page_lists_teams_and_links_them(client):
    response = client.get("/league/10")
    assert response.status_code == 200
    assert "Test League" in response.text
    assert 'href="/team/100"' in response.text      # outbound link exists


def test_leagues_index_lists_all_leagues(client):
    response = client.get("/leagues")
    assert 'href="/league/10"' in response.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_entities.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the queries**

```python
def league_detail(connection, league_id):
    """A league plus everything reachable from it."""
    league = connection.execute(
        "SELECT * FROM league WHERE id = ?", (league_id,)).fetchone()
    if league is None:
        return None
    return {
        "league": dict(league),
        "teams": rows(connection, """
            SELECT team.id, team.name, COUNT(absence.id) AS absences
            FROM absence
            JOIN team ON team.id = absence.team_id
            WHERE absence.league_id = ?
            GROUP BY team.id, team.name ORDER BY absences DESC
        """, (league_id,)),
        "seasons": rows(connection, """
            SELECT id, name, is_current FROM season
            WHERE league_id = ? ORDER BY name DESC
        """, (league_id,)),
        "types": rows(connection, """
            SELECT injury_type.name AS type, COUNT(*) AS n,
                   ROUND(AVG(absence.duration_days), 1) AS avg_days
            FROM absence LEFT JOIN injury_type ON injury_type.id = absence.type_id
            WHERE absence.league_id = ? AND absence.category = 'injury'
            GROUP BY type ORDER BY n DESC LIMIT 10
        """, (league_id,)),
    }
```

- [ ] **Step 4: Add routes and templates**

`/leagues` (index, grouped by country) and `/league/{id}`. The detail page shows breadcrumbs, stat tiles, and linked tables for teams / seasons / types. Return 404 via `HTTPException` when `league_detail` returns `None`.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/test_entities.py -v
git add -A && git commit -m "feat: league index and detail pages"
```

---

### Task 9: Team pages

Same shape. `team_detail` returns: the team, its squad (from `player_season`, most recent season), absences, transfers in and out (using the new indexes), and injury burden. Links out to player, league, season.

**Test:** `/team/100` contains `href="/player/5001"` and `href="/league/10"`.

---

### Task 10: Injury type pages

`type_detail` returns: the type, players affected (ranked by occurrences), average duration and games missed, and a position breakdown. Links out to player and absence rows.

**Test:** `/type/500` contains the type name and at least one `href="/player/`.

---

### Task 11: Season pages

`season_detail` returns: the season, its league, absences within it, and players with recorded minutes. Links out to league, team, player.

**Test:** `/season/77` contains `href="/league/10"`.

---

### Task 12: Player page expansion

**Files:** modify `app/queries/entities.py` (`player_timeline`), `app/templates/pages/player.html`

Add to the existing page: per-season minutes from `player_season` (seasons linked), transfer history from `transfer` (clubs linked where resolvable), and current team. Every absence row links to team / league / type / season.

**Test:** `/player/5001` contains `href="/team/100"` and a minutes figure.

---

### Task 13: Absences list with category filter

**Files:** modify `app/queries/absences.py`, `app/main.py`, create `app/templates/pages/absences.html`, `app/templates/partials/absence_rows.html`

- [ ] **Step 1: Write the failing tests**

```python
def test_absences_defaults_to_injuries_only(client):
    assert client.get("/absences").status_code == 200


def test_absences_category_filter_returns_suspensions(client):
    response = client.get("/api/absences", params={"category": "suspended"})
    assert all(row["category"] == "suspended" for row in response.json()["items"])


def test_injuries_url_redirects_preserving_meaning(client):
    response = client.get("/injuries", follow_redirects=False)
    assert response.status_code == 302
    assert "category=injury" in response.headers["location"]
```

> **302, not 301.** A permanent redirect is cached hard by browsers and is
> effectively irreversible for anyone who has visited once. Use 302 until the
> new URL has settled.

- [ ] **Step 2: Implement**

Change `injury_list` to read from `absence` with a `category` parameter (`None` = all). Keep the function name and its `category='injury'` default so existing callers are unaffected. Add `/absences` page + `/api/absences`, and a 301 from `/injuries`.

Every row links player / team / league / type. Filter changes and paging use htmx to swap `partials/absence_rows.html` into the table body.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/ -q
git add -A && git commit -m "feat: absences list with category filter and htmx paging"
```

---

## Chunk 4: Rates, Search, Dashboard

### Task 14: Injury rate per 1000 minutes

**Files:** create `app/queries/rates.py`, `tests/test_rates.py`

- [ ] **Step 1: Write the failing test — the threshold is the point**

```python
MINUTES_FLOOR = 450


def test_excludes_players_below_the_minutes_floor(connection):
    """A player with 90 minutes and one injury would score 11.1 per 1000 —
    twenty times a regular starter, purely as an artefact of a tiny
    denominator. Such players must not appear in a ranking."""
    ranked = rates.by_player(connection, season_id=77)
    assert all(row["minutes_played"] >= MINUTES_FLOOR for row in ranked)


def test_reports_minutes_alongside_every_rate(connection):
    """The basis must always be visible so a reader can judge the number."""
    for row in rates.by_player(connection, season_id=77):
        assert row["minutes_played"] is not None
        assert row["rate_per_1000"] is not None
```

- [ ] **Step 2: Implement**

```python
"""Injury rate per 1000 minutes — counts normalised by playing time."""
from app.db import rows

# ~5 full matches. Below this the denominator is too small for a rate to mean
# anything: one injury on 90 minutes reads as 11.1 per 1000, which would top
# every ranking while describing nothing.
MINUTES_FLOOR = 450


def by_player(connection, season_id, limit=50):
    return rows(connection, """
        SELECT player.id, player.name, player.position,
               player_season.team_id, player_season.minutes_played,
               COUNT(absence.id) AS injuries,
               ROUND(COUNT(absence.id) * 1000.0 / player_season.minutes_played, 2)
                 AS rate_per_1000
        FROM player_season
        JOIN player ON player.id = player_season.player_id
        LEFT JOIN absence ON absence.player_id = player_season.player_id
                         AND absence.season_id = player_season.season_id
                         AND absence.category = 'injury'
        WHERE player_season.season_id = ?
          AND player_season.minutes_played >= ?
        GROUP BY player.id, player.name, player.position,
                 player_season.team_id, player_season.minutes_played
        ORDER BY rate_per_1000 DESC, injuries DESC
        LIMIT ?
    """, (season_id, MINUTES_FLOOR, limit))
```

- [ ] **Step 3: Surface it**

Add a rate table to season and team pages. Every rate cell shows `minutes_played` beside it. Add a footnote naming the floor: *"Players with under 450 minutes are excluded — too few minutes for a meaningful rate."*

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/test_rates.py -v
git add -A && git commit -m "feat: injury rate per 1000 minutes with a minutes floor"
```

---

### Task 15: Global search

**Files:** create `app/queries/search.py`, `app/templates/partials/search_results.html`, `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

```python
def test_search_matches_players_by_prefix(connection):
    assert any(r["kind"] == "player" for r in search.search(connection, "A. Pl"))


def test_search_is_case_insensitive(connection):
    assert search.search(connection, "a. pl") == search.search(connection, "A. Pl")


def test_short_queries_return_nothing(connection):
    """One-character queries would match thousands of rows and are never useful."""
    assert search.search(connection, "a") == []
```

- [ ] **Step 2: Implement**

```python
def search(connection, query, per_kind=8):
    """Prefix search across entities. Returns [] for queries under 2 chars.

    Prefix (`q%`) rather than substring (`%q%`) so SQLite can use the indexes;
    at 13k players a scan is survivable but needless.
    """
    if not query or len(query.strip()) < 2:
        return []
    like = f"{query.strip()}%"
    results = []
    for kind, sql in (
        ("player", "SELECT id, name FROM player WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
        ("team",   "SELECT id, name FROM team   WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
        ("league", "SELECT id, name FROM league WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
    ):
        results.extend({**row, "kind": kind} for row in rows(connection, sql, (like, per_kind)))
    return results
```

- [ ] **Step 3: Wire the header input**

```html
<input type="search" name="q" placeholder="Search players, teams, leagues…"
       hx-get="/search" hx-trigger="keyup changed delay:200ms"
       hx-target="#search-results">
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/test_search.py -v
git add -A && git commit -m "feat: global prefix search across entities"
```

---

### Task 16: Dashboard

**Files:** modify `app/main.py`, `app/queries/overview.py`, create `app/templates/pages/dashboard.html`

- [ ] **Step 1: Write the failing test**

```python
def test_dashboard_links_into_every_view(client):
    response = client.get("/")
    for href in ("/absences", "/players", "/teams", "/leagues", "/seasons",
                 "/types", "/analytics", "/coverage"):
        assert f'href="{href}"' in response.text


def test_dashboard_warns_about_coverage(client):
    assert "coverage" in client.get("/").text.lower()
```

- [ ] **Step 2: Build it**

Three bands per the spec: stat row (each tile linked), coverage caveat banner linking to `/coverage`, then one summary card per view showing its top 5 with a "view all" link. Move the old coverage page to `/coverage`.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/ -q
git add -A && git commit -m "feat: dashboard summarising every view"
```

---

### Task 17: Coverage page rewrite and the ramp chart

**Files:** modify `app/templates/pages/coverage.html`, `app/queries/overview.py`

- [ ] **Step 1: Replace the stale claims**

Delete *"History depth is provisional. Sparse older coverage may reflect trial-account restrictions; it is not presented as a settled limitation."* — this was settled on 2026-07-27. Replace with the measured position: domestic leagues expose exactly 3 seasons (2024/25–2026/27) as a hard plan limit; UEFA cups reach back to 2000.

Replace the "Year 1 / Year 2 / Year 3" table, which encodes the old 3-year model and cannot represent 62 competitions.

- [ ] **Step 2: Chart the ramp**

Read the `coverage_<year>` rows from `data_quality` and render as a line chart with the caveat text beside it — including that the series changes composition in 2024 (cups-only before, cups plus 58 domestic leagues after).

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/ -q
git add -A && git commit -m "feat: coverage page reflects measured plan limits, chart the ramp"
```

---

### Task 18: Link the analytics page

**Files:** modify `app/templates/pages/analytics.html`

Every aggregate row becomes a link: type rows → `/type/{id}`, league rows → `/league/{id}`, position/age/nationality rows → `/absences?<filter>`. No new queries — the ids need adding to the existing `SELECT`s in `analytics.py`.

**Test:** `/analytics` contains `href="/type/` and `href="/league/`.

---

## Final verification

- [ ] `uv run pytest tests/ -q` — all green
- [ ] `uv run python -m app.etl` — rebuilds cleanly with new indexes
- [ ] Manual pass: from the dashboard, reach a player via search, then navigate player → team → league → season → back to a player without typing a URL
- [ ] Check light and dark mode, and 375px width
- [ ] Confirm `/injuries` still resolves and `/api/injuries` still returns injuries only
