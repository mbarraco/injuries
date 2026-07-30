# Two-Vendor Design Revamp Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Sportmonks and API-Football to matching nav/page hierarchies, give each a distinct visual identity, and apply the UX fixes found along the way — per `docs/superpowers/specs/2026-07-30-two-vendor-design-revamp-design.md`.

**Architecture:** Sportmonks moves from unprefixed routes/templates into `/sportmonks/*` + `templates/sportmonks/`, mirroring the existing `/af/*` + `templates/af/` split exactly. `/api/*` is frozen and untouched. One `--accent` CSS override per vendor, driven by a `data-vendor` body attribute derived from a (newly consistent) `active` naming convention.

**Tech Stack:** FastAPI + Jinja2 + htmx, SQLite, pytest. No new dependencies.

---

## Chunk 1: Shared auth + active-prefix convention (foundation)

- [ ] **Step 1: Move `verify_auth`/`HTTPBasic()` into `auth.py`**
  - Modify: `app/auth.py` — add `security = HTTPBasic()` and `async def verify_auth(...)` (moved verbatim from `main.py`).
  - Modify: `app/main.py` — delete the local `security`/`verify_auth`, `from app import auth` already present, use `auth.verify_auth` in every `Depends(...)`.
  - Modify: `app/af_routes.py` — delete its duplicate `security`/`verify_auth`, import `auth.verify_auth` instead. Delete the now-stale comment about avoiding circular import.
  - Run: `uv run pytest tests/ -q` — expect 275 passed (no behavior change).
  - Commit: `refactor: share verify_auth via auth.py instead of duplicating it`

- [ ] **Step 2: Rename Sportmonks' `active` values to a `sportmonks-` prefix**
  - Modify: `app/main.py` — every `"active": "X"` becomes `"active": "sportmonks-X"` (dashboard, absences, players, teams, leagues, seasons, types, coverage, analytics, admin, search — including the ones inside `admin/matrix*` breadcrumbs dicts, and note `page_player`'s current `"active": "injuries"` is already a latent bug — it should be `"sportmonks-players"` to match the nav item it's supposed to highlight).
  - Modify: `app/templates/base.html` — every Sportmonks nav `class="{{ 'active' if active == 'X' ...}}"` becomes `active == 'sportmonks-X'`.
  - Run: `uv run pytest tests/ -q` — check for failures asserting exact `active` values (grep first: `grep -rn '"active"' tests/`) and update those assertions.
  - Commit: `refactor: prefix Sportmonks active-nav values for vendor-detection`

- [ ] **Step 3: Derive `data-vendor` from `active` in `base.html`**
  - Modify: `app/templates/base.html` — add near the top: `{% set vendor = 'af' if active and active.startswith('af-') else ('sportmonks' if active and active.startswith('sportmonks-') else none) %}`, then `<body{% if vendor %} data-vendor="{{ vendor }}"{% endif %}>`.
  - Test: add `tests/test_visual_identity.py` — one test per vendor asserting `data-vendor="sportmonks"` / `data-vendor="af"` appears in the response body for a representative page from each, and asserting it's **absent** from `/` once that route exists (Chunk 4).
  - Run: `uv run pytest tests/test_visual_identity.py -v` — expect the two vendor assertions to pass now; the `/` one will fail until Chunk 4 lands (fine — note it as a known pending failure, or write it after Chunk 4 instead).
  - Commit: `feat: derive data-vendor body attribute for CSS accent switching`

- [ ] **Step 4: CSS accent-per-vendor + smaller UX fixes**
  - Modify: `app/static/style.css`:
    - Add `body[data-vendor="af"] { --accent: #8b5cf6; }` right after the existing `:root`/`:root[data-theme="dark"]` blocks (before the dark-mode media query, so dark mode's own `--accent` still applies first and this overrides it for `af` regardless of theme — verify by checking cascade order, dark theme block sets `--accent: #5b8dff`, so the `data-vendor="af"` rule must come AFTER both the light and dark theme blocks to win; place it last among the token blocks).
    - Add `.nav-group-label::before { content: '●'; margin-right: 5px; }` with `.nav-group[data-vendor="sportmonks"] .nav-group-label::before { color: #2f6df6; }` and `.nav-group[data-vendor="af"] .nav-group-label::before { color: #8b5cf6; }` (see Chunk 3 for the `data-vendor` attribute on nav groups themselves).
    - Add `.nav-toggle-label:focus-visible { outline: none; box-shadow: var(--focus-ring); }`.
    - Add a `.skip-link` style: visually hidden by default (`position: absolute; left: -999px;`), visible on focus (`left: 14px; top: 14px; z-index: 40; background: var(--surface); padding: 8px 14px; border-radius: var(--radius-sm);`).
    - Add `.theme-toggle` button style (small icon-button, matches `.sidebar-foot a` sizing).
  - Run: `uv run pytest tests/ -q` — CSS has no test coverage, this step just needs a visual sanity check (no automated test — note this in the commit message).
  - Commit: `style: add per-vendor accent override and small accessibility fixes`

---

## Chunk 2: Skip-link, theme toggle, Home nav entry (small, self-contained UX additions to base.html)

- [ ] **Step 1: Add skip-to-content link**
  - Modify: `app/templates/base.html` — as the very first element inside `<body>`, before the nav-toggle checkbox: `<a href="#main-content" class="skip-link">Skip to content</a>`. Add `id="main-content"` to the `<main>` element.
  - Test: add to `tests/test_htmx.py` or a new small test asserting `skip-link` and `id="main-content"` both appear in any page response.
  - Run: `uv run pytest -k skip -q`
  - Commit: `feat: add skip-to-content link for keyboard navigation`

- [ ] **Step 2: Add manual light/dark theme toggle**
  - Modify: `app/templates/base.html` — add a button in `.sidebar-foot`: `<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Toggle light/dark theme">◐</button>`.
  - Create: `app/static/theme.js` —
    ```js
    (function () {
      var root = document.documentElement;
      var stored = localStorage.getItem('theme');
      if (stored) root.setAttribute('data-theme', stored);
      document.getElementById('theme-toggle').addEventListener('click', function () {
        var current = root.getAttribute('data-theme') ||
          (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        var next = current === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
      });
    })();
    ```
  - Modify: `app/templates/base.html` — add `<script src="/static/theme.js"></script>` alongside the existing chart/htmx script tags. Note: `data-theme` must be set on `<html>` (`document.documentElement`), matching the existing CSS selector `:root[data-theme="dark"]` — `:root` in CSS refers to `<html>`, not `<body>`, so this must NOT be confused with the `data-vendor` attribute which lives on `<body>`.
  - Run: manual check only (no server-side test for client JS); confirm `uv run pytest tests/ -q` still green (no route changes).
  - Commit: `feat: add manual light/dark theme toggle, persisted in localStorage`

- [ ] **Step 3: Add "Home" nav entry above both vendor groups**
  - Modify: `app/templates/base.html` — add `<div class="nav-group"><a href="/" class="{{ 'active' if active == 'home' else '' }}">← Home</a></div>` as the first `nav-group`, before the Sportmonks group.
  - (The `/` route itself is added in Chunk 4 — this step only adds the link; it 404s until then, which is fine since Chunk 4 follows immediately in this same plan.)
  - Commit: `feat: add Home nav entry linking to the vendor picker`

---

## Chunk 3: Route split — `app/sportmonks_routes.py`, prefix restructuring, template move

This is the largest mechanical chunk. Do it as one focused pass, verify with the full suite, then commit once — splitting it further would leave the app in a broken intermediate state.

- [ ] **Step 1: Create `templates/sportmonks/` and move every Sportmonks-only template into it**

  Move (via `git mv`) these files from `app/templates/` to `app/templates/sportmonks/`:
  `absences.html analytics.html coverage.html dashboard.html league.html leagues.html player.html players.html search.html season.html seasons.html team.html teams.html type.html types.html` and the whole `admin/` subdirectory.

  Leave at the root: `base.html`, `macros.html`, `home.html` (new, Chunk 4), `partials/search_results.html` (used by both vendors' search — see Chunk 5).

  Run: `find app/templates -maxdepth 1 -type f` to confirm only `base.html`, `macros.html` remain at that level (plus `home.html` once added).

- [ ] **Step 2: Create `templates/sportmonks/_macros.html` with the vendor-specific macros**

  Move `entity_link`, `transfer_fee`, `transfer_type`, `transfer_totals`, and `matrix` out of `app/templates/macros.html` into a new `app/templates/sportmonks/_macros.html`, updating every hardcoded path:
  - `entity_link`: `href="/{{ kind }}/{{ id }}"` → `href="/sportmonks/{{ kind }}/{{ id }}"`.
  - `matrix`: `/admin/matrix/{{ data.measure }}/...` → `/sportmonks/admin/matrix/{{ data.measure }}/...` (both occurrences — the drill link and the cell-detail link).
  - `transfer_fee`, `transfer_type`, `transfer_totals` — no path changes needed, move as-is.

  `app/templates/macros.html` keeps: `breadcrumbs`, `stat`, `count_heading`, `page_link`, `rate_empty_state`, `empty_state` — none of these hardcode a vendor path, confirmed in spec review.

- [ ] **Step 3: Update every moved Sportmonks template's imports**

  In each of the 15 moved files, change the import line from:
  `{% import "macros.html" as macros %}`
  to:
  `{% import "../macros.html" as macros %}{% import "_macros.html" as sm %}`

  and rename every call site: `macros.entity_link(...)` → `sm.entity_link(...)`, `macros.matrix(...)` → `sm.matrix(...)`, `macros.transfer_fee(...)` → `sm.transfer_fee(...)`, `macros.transfer_type(...)` → `sm.transfer_type(...)`, `macros.transfer_totals(...)` → `sm.transfer_totals(...)`. Leave `macros.breadcrumbs`, `macros.stat`, `macros.count_heading`, `macros.page_link`, `macros.rate_empty_state`, `macros.empty_state` calls unchanged (still resolved via the `macros` import, now pointing at `../macros.html`).

  `admin/*.html` templates are one directory deeper (`templates/sportmonks/admin/`), so their relative import is `../../macros.html` and `../_macros.html`.

  Also: every `href="/absences"`, `href="/players"`, `href="/{{ ... }}"` literal (non-macro) link inside these templates needs the `/sportmonks` prefix — grep for `href="/` across the moved files and fix each one (this includes breadcrumb trails passed from routes — see Step 4 — and any inline "All X →" links).

- [ ] **Step 4: Create `app/sportmonks_routes.py`, moving every Sportmonks page route out of `main.py`**

  Mirror `af_routes.py`'s shape: `router = APIRouter(prefix="/sportmonks")`, import `auth.verify_auth` (from Chunk 1), `from app import matrix, queries`. Move every `@app.get(...)` route from `main.py` whose response is an HTML page (dashboard, coverage, analytics, absences, players, player, leagues, league, teams, team, seasons, season, types, type, admin, admin/matrix*, search) into this file as `@router.get(...)`, dropping the leading path segment that's now the router prefix (e.g. `/absences` stays `/absences` since the prefix supplies `/sportmonks`; but the OLD `/` dashboard route becomes `@router.get("/")`).

  Every `TemplateResponse(request, "X.html", ...)` call becomes `TemplateResponse(request, "sportmonks/X.html", ...)` (or `"sportmonks/admin/X.html"`). Every `"active": "sportmonks-X"` value from Chunk 1's rename stays as-is (already correct). Every breadcrumb dict's `href` (e.g. `{"href": "/admin", ...}`) gains the `/sportmonks` prefix.

  Delete the `/injuries` legacy redirect route entirely (spec decision: clean cutover, no redirects) — do NOT move it to `/sportmonks/injuries`.

  `main.py` keeps: FastAPI app creation, static mount, `app.include_router(af_routes.router)`, `app.include_router(sportmonks_routes.router)`, every `/api/*` route **exactly as it is, untouched, unprefixed** (do not move these — this is the frozen contract), and the new `/` neutral-landing route (Chunk 4).

- [ ] **Step 5: Fix `base.html`'s nav hrefs**

  Every Sportmonks `<a href="/X">` in the nav becomes `<a href="/sportmonks/X">` (dashboard→`/sportmonks/`, absences, players, teams, leagues, seasons, types→`/sportmonks/types`, coverage, admin). API-Football nav entries are unaffected (already `/af/*`).

- [ ] **Step 6: Run the full suite and fix fallout**

  Run: `uv run pytest tests/ -q`

  Expect failures in every Sportmonks-facing test file (`test_api.py`, `test_dashboard.py`, `test_absences.py`, `test_entities.py`, `test_analytics.py`, `test_coverage.py`, `test_search.py`, `test_htmx.py`, `test_dimensions.py`, `test_matrix.py`, `test_transfers.py`) wherever they hit an old unprefixed page path — these need their URLs updated to `/sportmonks/...`. **Do NOT touch any assertion or fixture that hits `/api/*`** — those must still pass unmodified; if one fails, that's a sign `/api/*` was accidentally touched in Step 4, and that's the bug to fix, not the test.

  Fix each failing test file's page URLs, re-run, repeat until green.

  - [ ] **Step 6a: Write the cutover test**
    - Modify: `tests/test_api.py` (or a new `tests/test_cutover.py`) — add a test asserting every old unprefixed page path 404s: `/`, `/absences`, `/players`, `/player/1`, `/teams`, `/team/1`, `/leagues`, `/league/1`, `/seasons`, `/season/1`, `/types`, `/type/1`, `/coverage`, `/analytics`, `/admin`, `/search`, `/injuries` — loop over the list, `assert client.get(path).status_code == 404` for each **except** `/` (which will return 200 once Chunk 4's neutral landing lands — if running this test before Chunk 4, expect `/` to still 404 or be commented pending that chunk).
    - Run: `uv run pytest tests/test_cutover.py -v` (or wherever added) — expect all pass.

  - [ ] **Step 6b: Write the frozen-contract test**
    - Modify: `tests/test_api.py` — add a test that calls every `/api/*` route with the same fixture data used before this plan started and asserts identical status codes and (for a couple of representative routes) identical JSON keys/shape. This is a regression guard specifically for "did the router split accidentally touch `/api/*`."
    - Run: `uv run pytest tests/test_api.py -v` — expect pass.

- [ ] **Step 7: Commit**
  ```bash
  git add -A
  git commit -m "$(cat <<'EOF'
refactor: split Sportmonks routes into /sportmonks/*, mirroring /af/*

Sportmonks templates move into templates/sportmonks/ and its page
routes into a new sportmonks_routes.py, matching the structure
af_routes.py already established. /api/* is untouched -- frozen per
AGENTS.md. Old unprefixed page paths are removed with no redirect
shim, per the design's clean-cutover decision.
EOF
  )"
  ```

---

## Chunk 4: Neutral landing page (`/`)

- [ ] **Step 1: Write `templates/home.html`**

  Two peer cards, one per vendor, each showing a handful of headline stats (reuse `queries.overview()` / `af_queries.overview()`, already computed for each dashboard) and an "Enter →" link into `/sportmonks/` / `/af/`. Include one sentence per card on the grain difference (spell-measured vs. fixture-appearance) so the caveat is visible before a reader picks a side. No `data-vendor` on this page — each card scopes its own accent locally via a wrapping class (`<div class="vendor-card" data-vendor-scope="sportmonks">` / `...="af"`), and `style.css` needs a scoped-not-global version of the accent rule: `.vendor-card[data-vendor-scope="af"] { --accent: #8b5cf6; }` (a card-scoped variable override, distinct from the body-level one).

- [ ] **Step 2: Add the route**
  - Modify: `app/main.py` — add `@app.get("/", response_class=HTMLResponse)` rendering `home.html` with `{"active": "home"}` plus both vendors' `overview()` results.
  - Run: `uv run pytest tests/test_cutover.py -v` — the `/` case should now assert 200, not 404; update that test's list accordingly (`/` moves from the 404 list to its own explicit 200 assertion).

- [ ] **Step 3: Write the route test**
  - Test: add to `tests/test_api.py` or a new `tests/test_home.py` — `GET /` returns 200, contains both "Sportmonks" and "API-Football" (or their card headings), and contains **no** `data-vendor` attribute on `<body>` (completing the Chunk 1 Step 3 test that was pending this chunk).
  - Run: `uv run pytest -k home -q`

- [ ] **Step 4: Commit**
  ```bash
  git add app/templates/home.html app/main.py app/static/style.css tests/
  git commit -m "feat: add neutral landing page presenting both vendors as peers"
  ```

---

## Chunk 5: New pages — `/af/coverage`, `/af/reasons` + `/af/reason/{reason}`, `/sportmonks/transfers`

- [ ] **Step 1: `/af/coverage`**
  - No new query function needed — `af_queries.quality_metrics()` already exists.
  - Create: `app/templates/af/coverage.html`, structurally mirroring `templates/sportmonks/coverage.html`, explaining the grain-vs-backfill distinction between the two vendors' caveats (per spec).
  - Modify: `app/af_routes.py` — add `@router.get("/coverage", response_class=HTMLResponse)`.
  - Modify: `app/templates/base.html` — add the nav entry to the API-Football group's Quality section.
  - Test: add to `tests/test_af_routes.py` — `GET /af/coverage` returns 200.
  - Run: `uv run pytest -k af_coverage -q`
  - Commit: `feat: add /af/coverage, the peer of Sportmonks' coverage page`

- [ ] **Step 2: `af_queries.reasons_index()` and `reason_detail()`**
  - Modify: `app/af_queries.py` — add `reasons_index(connection)` mirroring `queries.types_index()`'s shape (reason, category, row_count, ordered by volume) and `reason_detail(connection, reason)` mirroring `queries.type_detail()`'s shape: players affected (via a fresh inline query joining `af_absence`/`af_player`/`af_player_season`, filtered `WHERE reason = ?` — **do not** attempt to reuse `by_position()` unmodified; per spec-review correction it takes no filter parameter, write this as its own query, following `type_detail()`'s inline-query pattern at `queries.py:759`).
  - Test: add to `tests/test_af_queries.py` — `reasons_index()` returns the fixture's known reasons; `reason_detail()` for a known reason returns players/position breakdown; `reason_detail()` for an unknown reason returns `None`.
  - Run: `uv run pytest -k reason -q`
  - Commit: `feat: add af_queries.reasons_index and reason_detail`

- [ ] **Step 3: `/af/reasons` + `/af/reason/{reason}` routes and templates**
  - Create: `app/templates/af/reasons.html` (mirrors `sportmonks/types.html`), `app/templates/af/reason.html` (mirrors `sportmonks/type.html`, using breadcrumbs and `GRAIN_NOTE`).
  - Modify: `app/af_routes.py` — add both routes. `/af/reason/{reason}` takes `reason: str` as a path param (URL-encoded reason string, per the spec's noted schema divergence — no numeric id exists for this entity).
  - Modify: `app/templates/base.html` — add the nav entry.
  - Test: add to `tests/test_af_routes.py` — index renders, detail renders for a known reason, 404 for an unknown one.
  - Run: `uv run pytest -k af_reason -q`
  - Commit: `feat: add /af/reasons and /af/reason/{reason}, the peer of Sportmonks' injury types`

- [ ] **Step 4: `queries.transfers_index()`**
  - Modify: `app/queries.py` — add `transfers_index(connection, page=1, per_page=...)` using the existing `_TRANSFER_SELECT`, paginated; a category/type breakdown grouped by `type_id`/`transfer_type` (reusing the existing type-name join, matching the convention already used for `UNNAMED_TRANSFER_TYPE`); fee totals via `_transfer_summary()`; a by-year breakdown (`SUBSTR(date, 1, 4)` grouped, mirroring `af_queries.transfers_by_year()`'s shape).
  - Test: add to `tests/test_transfers.py` — totals, pagination, and the by-year grouping all check out against the fixture data.
  - Run: `uv run pytest -k transfers_index -q`
  - Commit: `feat: add queries.transfers_index`

- [ ] **Step 5: `/sportmonks/transfers` route and template**
  - Create: `app/templates/sportmonks/transfers.html`, mirroring `templates/af/transfers.html`'s structure (overview stats, category table, by-year table), using the *root* `macros.html` for `breadcrumbs`/`stat`/`count_heading` and `sportmonks/_macros.html` for `transfer_fee`/`transfer_type`/`transfer_totals`/`entity_link`.
  - Modify: `app/sportmonks_routes.py` — add `@router.get("/transfers", response_class=HTMLResponse)`.
  - Modify: `app/templates/base.html` — add the nav entry to Sportmonks' Explore section.
  - Test: add to `tests/test_transfers.py` or a route test file — `GET /sportmonks/transfers` returns 200 and contains expected totals.
  - Run: `uv run pytest -k sportmonks_transfers -q`
  - Commit: `feat: add /sportmonks/transfers, the peer of API-Football's transfers page`

- [ ] **Step 6: Full suite**
  - Run: `uv run pytest tests/ -q` — expect all green, count now above 275 (new tests added).

---

## Chunk 6: Vendor-scoped search, breadcrumb/grain-note consistency

- [ ] **Step 1: Vendor-scoped search**
  - Modify: `app/main.py` (or `sportmonks_routes.py` per Chunk 3) — rename `/search` to `/sportmonks/search` (already done implicitly by Chunk 3's move if `page_search` was included in the moved-routes list — verify it's there; if not, move it now).
  - Modify: `app/af_routes.py` — add `@router.get("/search", response_class=HTMLResponse)` mirroring `page_search` exactly but calling `af_queries.search()` and rendering an `af/search.html` (new file, mirrors `sportmonks/search.html`) and the shared `partials/search_results.html` fragment for the htmx path (verify this partial doesn't hardcode a Sportmonks-only path in its entity links — if it does, it needs a vendor-aware variant or a passed-in link-builder; check `app/templates/partials/search_results.html` before assuming it's reusable as-is).
  - Modify: `app/templates/base.html` — the single search form's `action` and `hx-get`/`hx-target` attributes become conditional on `vendor` (the variable from Chunk 1 Step 3): `action="{{ '/af/search' if vendor == 'af' else '/sportmonks/search' }}"`. On the neutral landing page (`vendor` is `none`), omit the search form entirely.
  - Test: add to `tests/test_search.py` — searching while `af` is active returns API-Football entities; searching while `sportmonks` is active returns Sportmonks entities; the search form is absent from `/`'s response body.
  - Run: `uv run pytest -k search -q`
  - Commit: `feat: make sidebar search vendor-scoped instead of always hitting Sportmonks`

- [ ] **Step 2: Breadcrumbs everywhere**
  - Modify: `app/sportmonks_routes.py` — `page_player` gains a `"breadcrumbs"` context value (it currently has none), following the same trail shape as `league`/`team`/`type` (`Home › Players › {name}`) — via `sm.breadcrumbs` in the template.
  - Modify: `app/templates/sportmonks/player.html` — add the `sm.breadcrumbs(...)` call, mirroring `team.html`.
  - Modify: `app/af_routes.py` and each of `af/player.html`, `af/team.html`, `af/league.html`, `af/reason.html` (from Chunk 5) — add breadcrumb context + `af.breadcrumbs(...)` calls. **Note:** `af/_macros.html` has no `breadcrumbs` macro today — it can reuse the root `macros.breadcrumbs` directly (already imported in every af template) since that macro is generic and takes a trail list with no hardcoded path; only the trail's `href` values need `/af/...` prefixes, supplied by the route, not the macro.
  - Test: for each of the 4 af pages plus `sportmonks/player.html`, assert the response contains a `breadcrumbs` nav element (`grep`-style substring check, e.g. `'aria-label="Breadcrumb"'` in body).
  - Run: `uv run pytest -k breadcrumb -q`
  - Commit: `feat: add breadcrumbs to every remaining detail page`

- [ ] **Step 3: Grain-note consistency on `/af/*`**
  - Modify: `app/af_routes.py` — pass `af_queries.GRAIN_NOTE` into the context for `page_analytics`, `page_leagues`, `page_league`, `page_teams`, `page_team` (currently missing it per the audit in the spec).
  - Modify: the corresponding templates (`af/analytics.html`, `af/leagues.html`, `af/league.html`, `af/teams.html`, `af/team.html`) — add `{{ af.grain_note(grain_note) }}` near the top of `{% block content %}`, matching how `af/player.html`/`af/absences.html` already do it.
  - Test: for each of the 5 pages, assert the grain-note text appears in the response.
  - Run: `uv run pytest -k grain_note -q`
  - Commit: `feat: make grain-note context banner consistent across all af pages`

---

## Chunk 7: Nav restructure into labeled Overview/Explore/Quality groups per vendor

- [ ] **Step 1: Restructure `base.html`'s nav markup**

  Replace the current flat per-vendor `<div class="nav-group">` blocks with, for EACH vendor, three sub-groups under one vendor-labeled wrapper:

  ```html
  <div class="nav-vendor" data-vendor="sportmonks">
    <div class="nav-group-label">Sportmonks</div>
    <div class="nav-group">
      <a href="/sportmonks/" class="{{ 'active' if active == 'sportmonks-dashboard' else '' }}">Dashboard</a>
      <a href="/sportmonks/absences" class="{{ 'active' if active == 'sportmonks-absences' else '' }}">Absences</a>
      <a href="/sportmonks/analytics" class="{{ 'active' if active == 'sportmonks-analytics' else '' }}">Analytics</a>
    </div>
    <div class="nav-group">
      <a href="/sportmonks/players" ...>Players</a>
      <a href="/sportmonks/teams" ...>Teams</a>
      <a href="/sportmonks/leagues" ...>Leagues</a>
      <a href="/sportmonks/transfers" ...>Transfers</a>
      <a href="/sportmonks/seasons" ...>Seasons</a>
      <a href="/sportmonks/types" ...>Injury types</a>
    </div>
    <div class="nav-group">
      <a href="/sportmonks/coverage" ...>Coverage &amp; Quality</a>
    </div>
    <div class="nav-group nav-group-admin">
      <a href="/sportmonks/admin" ...>Admin</a>
    </div>
  </div>
  <div class="nav-vendor" data-vendor="af">
    <div class="nav-group-label">API-Football</div>
    <div class="nav-group">Dashboard · Absences · Analytics</div>
    <div class="nav-group">Players · Teams · Leagues · Transfers · Reasons</div>
    <div class="nav-group">Coverage</div>
  </div>
  ```

  (Write out full `href`/`active` values for every link, following the pattern shown for Sportmonks' first two groups above.)

- [ ] **Step 2: Style the restructured nav**
  - Modify: `app/static/style.css` — the `.nav-group-label::before` colored-dot rule from Chunk 1 Step 4 now targets `.nav-vendor[data-vendor] .nav-group-label::before` (adjust the selector to match the new wrapper). Add `.nav-group-admin { margin-top: 4px; } .nav-group-admin a { font-size: 12px; color: var(--soft); }` for the visually-subordinate Admin link.
  - Verify mobile nav still renders sensibly with the extra grouping (manual check — no automated test for this).

- [ ] **Step 3: Test the full nav renders and highlights correctly**
  - Modify: existing route tests (or add one consolidated nav test) — for one page per vendor, assert the correct nav link carries `class="active"` and no other link does.
  - Run: `uv run pytest -k nav -q`

- [ ] **Step 4: Commit**
  ```bash
  git add app/templates/base.html app/static/style.css tests/
  git commit -m "feat: restructure sidebar into matching Overview/Explore/Quality groups per vendor"
  ```

---

## Chunk 8: Final verification

- [ ] **Step 1: Full suite**
  - Run: `uv run pytest tests/ -q` — expect all green.

- [ ] **Step 2: Manual smoke test**
  - Run: `uv run uvicorn app.main:app --reload`, visit `/`, `/sportmonks/`, `/af/`, confirm accent color changes, dark/light toggle works, skip-link appears on Tab, search box retargets correctly between sections, mobile nav (resize browser) still opens/closes.

- [ ] **Step 3: Update `AGENTS.md` if any documented URL changed**
  - Check `AGENTS.md`'s "Commands" and "Architecture" sections for any reference to the old unprefixed Sportmonks page paths (the app itself is usually described via `uv run uvicorn app.main:app --reload`, which doesn't encode a path — likely no change needed, but verify).

- [ ] **Step 4: Final commit**
  ```bash
  git add -A
  git commit -m "chore: final verification pass for two-vendor design revamp"
  ```
