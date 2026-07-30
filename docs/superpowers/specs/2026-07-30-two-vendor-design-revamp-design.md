# Two-Vendor Design Revamp — Matching Hierarchies & Visual Separation

**Date:** 2026-07-30
**Status:** Approved, ready for implementation planning
**Builds on:** [2026-07-27-injury-app-redesign-design.md](2026-07-27-injury-app-redesign-design.md)
(the Sportmonks UI this mirrors) and
[2026-07-29-apifootball-ingestion.md](2026-07-29-apifootball-ingestion.md)
(the `/af` app this brings to parity).

## Purpose

The app grew two vendors at different times: Sportmonks got a full UX pass
(2026-07-27), and API-Football was bolted on afterward as "additive" — sharing
layout but living in one nav group with no internal structure, no visual
identity, and several pages missing relative to its peer. The request: make
the two vendors' hierarchies match, keep them visually distinguishable (the two
datasets measure absences at different grains and must never be silently
compared — see `AGENTS.md`), and apply general UX improvements found along the
way.

## Current state (measured, 2026-07-30)

| | Sportmonks | API-Football |
|---|---|---|
| Route ownership | `main.py`, 291 lines, everything inline | `af_routes.py`, its own module |
| Templates | flat under `templates/` | `templates/af/` |
| Nav | 3 unlabeled groups | 1 group, labeled "API-Football" |
| Entity pages | Players, Teams, Leagues, Seasons, Types | Players, Teams, Leagues, Transfers |
| Quality page | `/coverage` | *(none — `af_data_quality` exists, unexposed)* |
| Admin tooling | `/admin` (coverage matrices) | *(none)* |
| Transfers page | *(none — inline only)* | `/af/transfers` |
| Breadcrumbs | league/season/team/type only | *(none, anywhere)* |
| Search | one global box → `/search` (Sportmonks only) | `af_queries.search()` exists, no page wired to it |
| Theme | `data-theme` CSS ready, no toggle control | same |

Two concrete bugs this design fixes as a byproduct: the sidebar's single
search box silently searches Sportmonks data even while browsing `/af/*`, with
no indication; and `player.html` is the one Sportmonks detail page missing
breadcrumbs that its siblings already have.

## Decisions made in brainstorming

1. **Visual + structural separation** (not structural-only) — a consistent
   visual cue must make the current vendor identifiable anywhere in the app.
2. **Full URL peer treatment**: Sportmonks moves to `/sportmonks/*`, matching
   `/af/*`; `/` becomes a neutral landing page presenting both as equals.
3. **Clean cutover, no legacy redirects** for pages. `/api/*` (the JSON
   contract) is the one frozen exception. `AGENTS.md`'s actual invariant is
   scoped to one route — *"`/api/injuries` returns injuries only by default.
   External callers depend on it"* — this design extends that same caution to
   the whole `/api/*` family on the reasonable assumption that any of them
   could have an external caller; it does not move, gain a prefix, or change
   behavior, for any route under it.
4. Add `/af/coverage` (peer of `/coverage`).
5. Add `/sportmonks/transfers` (peer of `/af/transfers`) and `/af/reasons`
   (peer of `/types`). Leave `/admin` (coverage matrices) Sportmonks-only —
   heavy, measure-specific tooling, not a generic page type worth mirroring.

## Approach

**Full structural mirror**, chosen over two alternatives considered:

- *URL-only reprefixing* (keep `main.py` monolithic) — rejected: it would give
  the user-facing hierarchy symmetry while leaving the code that produces it
  lopsided, which is the same problem one layer down.
- *Also split `queries.py` into a package* — rejected as **out of scope**: a
  prior design (2026-07-27) proposed this and never did it; bundling it here
  makes an already-large diff larger for a goal (query-layer organization)
  the user didn't ask for. Left for a separate future pass.

## URL structure

```
/                        neutral landing — two peer cards, one per vendor
/sportmonks/             dashboard (was /)
/sportmonks/absences  /sportmonks/players  /sportmonks/teams  /sportmonks/leagues
/sportmonks/seasons   /sportmonks/types    /sportmonks/transfers      NEW
/sportmonks/analytics /sportmonks/coverage /sportmonks/admin/*
/sportmonks/search    (was /search)

/af/                     dashboard (unchanged)
/af/absences  /af/players  /af/teams  /af/leagues  /af/transfers  /af/analytics
/af/reasons   /af/reason/{reason}                                NEW
/af/coverage                                                     NEW
/af/search                                                       NEW

/api/*        FROZEN. Unprefixed, unchanged, untouched.
/af/api/*     unchanged.
```

Old unprefixed page routes (`/absences`, `/player/42`, `/types`, …) are removed
outright — no redirect shim. `/api/*` is not a page route and is unaffected.

**One asymmetric key type, kept honest rather than hidden**: `af_reason` has no
numeric id — the reason string itself is the key (`schema_af.sql`). So
`/af/reason/{reason}` takes a URL-encoded string where `/type/{id}` takes an
integer. Same position in the hierarchy, genuinely different underlying key —
matching every other place this project documents a real schema divergence
instead of papering over it.

## Navigation

Two labeled, colored nav groups with **identical internal structure**:

```
[vendor-color dot] Sportmonks           [vendor-color dot] API-Football
  Overview                                Overview
    Dashboard · Absences · Analytics        Dashboard · Absences · Analytics
  Explore                                 Explore
    Players · Teams · Leagues ·             Players · Teams · Leagues ·
    Transfers · Seasons · Types              Transfers · Reasons
  Quality                                 Quality
    Coverage                                Coverage
  Admin (small, muted)                    —
```

A **Home** entry sits above both groups, linking to `/`, so there's always a
way back to the picker. `Admin` stays visually subordinate (smaller text,
extra top margin) rather than a peer-weight nav item — present, not hidden,
not pretending to be symmetric.

**Search becomes vendor-scoped.** One box, not two: its form action and htmx
target retarget to `/sportmonks/search` or `/af/search` based on which
section's pages are currently active (derived from the existing `active`
context variable already passed to every template). On the neutral landing
page, where there is no current vendor, the search box is omitted entirely
rather than defaulting to either side.

**This requires a naming step that doesn't exist yet, called out explicitly
rather than assumed.** Only API-Football's `active` values are currently
prefixed (`af-dashboard`, `af-players`, …) — Sportmonks' are bare (`dashboard`,
`players`, `types`, …), a leftover of Sportmonks being the original,
unprefixed app. Deriving both the search target and the `data-vendor` body
attribute (below) from `active` requires every Sportmonks route handler's
context dict to gain a `sportmonks-` prefix on its `active` value — mechanical
but wide-reaching, same shape as the macro migration below, and should be its
own reviewable step in the implementation plan for the same reason.

## Visual identity

One mechanism, reusing the existing design-token system in `style.css` (the
same one that already drives light/dark via `:root[data-theme]`):

- A `data-vendor="sportmonks"` or `data-vendor="af"` attribute is set on
  `<body>` in `base.html`, derived from the same `active` prefix the
  vendor-scoped search uses (see above) — one signal, two consumers, rather
  than each route handler passing a separate flag. An override block re-points
  `--accent` (and only `--accent`) for each value — every component that
  already reads `var(--accent)` (links, active nav state, stat values, filter
  buttons, focus rings) repaints automatically. **No new components, no
  per-vendor duplication of the palette.**
- Sportmonks keeps its existing blue (`--accent: #2f6df6`) — no reason to
  change the established identity.
- API-Football gets a distinct hue, violet (`#8b5cf6`) — far enough from both
  the Sportmonks blue and the existing semantic `--good`/`--warn` colors to
  read unambiguously as "a different section," in both light and dark themes.
- Dark/light mode and vendor accent are independent axes — the toggle and the
  vendor context never interact.
- The neutral landing page sets no `data-vendor`; its two cards render each in
  their own accent locally (scoped, not global) so the picker itself shows
  both identities side by side.

This means any single element on any page — an active nav link, a stat tile,
a button — identifies which vendor's data you're looking at, without a
persistent banner competing for attention.

## New pages

### `/af/reasons` + `/af/reason/{reason}`

Peer of `/types` + `/type/{id}`. New `af_queries.reasons_index()` (mirrors
`types_index()`: reason, category, row_count, ordered by volume) and
`reason_detail(connection, reason)` (mirrors `type_detail()`: players
affected via `af.af_entity_link`, plus a by-position breakdown).

**Correction from spec review:** `type_detail()` does not call the standalone
`by_position()` — it has its own inline query filtered by `type_id`
(`queries.py:759`), and `af_queries.by_position()` takes no filter parameter
today. `reason_detail()` needs the same treatment as `type_detail()`: its own
inline query, `WHERE reason = ?` joined through `af_player_season` for
position, written fresh rather than reusing `by_position()` unmodified.

Carries `GRAIN_NOTE`, same as every other `/af/*` page that surfaces absence
counts.

### `/af/coverage`

Thin page over the already-computed `af_data_quality` table via the existing
`af_queries.quality_metrics()` — no new query logic. States explicitly how
this vendor's coverage caveat differs from Sportmonks': not a backfill ramp
over years, but a fixture-appearance grain with no spell id, and (per the
2026-07-30 transfers work already in the codebase) a transfer table whose
history is *not* bounded the way absences are.

### `/sportmonks/transfers`

Peer of `/af/transfers`. New `transfers_index()` in `queries.py`: paginated
list over all `transfer` rows via the existing `_TRANSFER_SELECT`, a
type/category breakdown (Loan/Transfer/Free Transfer, reusing the existing
`injury_type`-join convention already used for transfer types), fee totals
following the existing `_transfer_summary()` convention (fees-known count
alongside any total, never a bare sum), and a by-year breakdown. New
`templates/sportmonks/transfers.html`, structurally mirroring
`templates/af/transfers.html`.

## Code structure

- **New `app/sportmonks_routes.py`**, mirroring `app/af_routes.py`'s shape
  (router with `prefix="/sportmonks"`, its own page + `/api/*`-adjacent routes
  — note: this module's routes live under `/sportmonks/api/...` if any exist,
  distinct from the frozen top-level `/api/*`). `main.py` shrinks to: app
  creation, static mount, both routers included, and the single shared `/`
  neutral-landing route.
- **`verify_auth`/`HTTPBasic()` move into `auth.py`** as one real shared
  dependency. `af_routes.py` currently duplicates this pair specifically to
  avoid a circular import from `main.py`; splitting Sportmonks into its own
  module makes that duplication pointless in both directions, so this removes
  it rather than tripling it.
- **Templates split**: `templates/sportmonks/` (mirroring `templates/af/`)
  holds every Sportmonks-specific template. The shared root `templates/`
  keeps `base.html`, the new `home.html`, and `macros.html` — but only the
  genuinely vendor-neutral macros stay there (`breadcrumbs`, `stat`,
  `count_heading`, `page_link`, `rate_empty_state`, `empty_state` — all
  already parametrized with no hardcoded vendor path). Macros that hardcode a
  Sportmonks path (`entity_link` → `/{{kind}}/{{id}}`, `matrix` →
  `/admin/matrix/...`, `transfer_fee`/`transfer_type`/`transfer_totals`) move
  into a new `templates/sportmonks/_macros.html`, exactly mirroring the split
  `templates/af/_macros.html` already proved out. `entity_link`'s href gains
  the `/sportmonks` prefix as part of this move — a forced edit, since the
  route it points to is moving regardless of this refactor.

## UX improvements applied

- **Manual light/dark toggle**, sidebar footer, persisted in `localStorage`.
  The CSS (`:root[data-theme]`) has supported this since 2026-07-27; nothing
  has ever exposed a control for it.
- **Breadcrumbs made consistent**: added to `player.html` (the one Sportmonks
  detail page missing them) and to every `/af/*` detail page (player, team,
  league, the new reason detail), using a `templates/af/_macros.html`
  breadcrumbs call already following the same pattern as the shared one.
- **Grain-note banners made consistent** across `/af/*` pages that currently
  lack one despite showing absence counts (analytics, leagues index, teams
  index, league detail, team detail).
- **Skip-to-content link** — first focusable element on the page, visually
  hidden until focused. No such control exists today; keyboard users
  currently tab through the entire sidebar before reaching page content.
- **Visible focus state on the mobile nav toggle** (`.nav-toggle-label`),
  which currently has no explicit `:focus-visible` styling of its own.

## Testing

- Route test per new page: `/`, `/af/coverage`, `/af/reasons`,
  `/af/reason/{reason}`, `/sportmonks/transfers`.
- A cutover test: every old unprefixed Sportmonks page path (`/absences`,
  `/players`, `/player/1`, etc.) returns 404.
- A frozen-contract test: every existing `/api/*` route responds identically
  (same status, same JSON shape) before and after — this is the one thing in
  the whole diff that must show zero behavioral change.
- A vendor-scoped-search test: searching from an `/af/*` page returns
  API-Football entities; searching from a `/sportmonks/*` page returns
  Sportmonks entities.
- A visual-identity test: rendered `data-vendor` attribute matches the active
  section on a sample of pages from each vendor, and is absent on `/`.
- Existing suite (275 passing as of this writing) stays green throughout.

## Out of scope

- Splitting `queries.py` into a package.
- An API-Football peer for `/admin` (coverage matrices) — left intentionally
  asymmetric, by explicit decision in brainstorming.
- Any change to `/api/*` request/response shape, path, or auth.
- Legacy redirects from old unprefixed Sportmonks page paths.
- Rewriting git history for either committed `.db` file.

## Risks

- **Scope.** This touches `main.py`, adds a new router module, moves an
  entire template directory, and touches `style.css` — a large diff by
  nature of "make two grown-independently sections match." The existing test
  suite plus the new cutover/frozen-contract tests are the safety net.
- **The `/api/*` freeze is easy to violate by accident** while splitting
  `main.py` — the frozen-contract test exists specifically to catch a stray
  prefix change or import reshuffle that touches it unintentionally.
- **Template macro migration** (moving `entity_link` and friends into
  `templates/sportmonks/_macros.html`) touches every Sportmonks template's
  import line — mechanical, but wide; worth doing as its own reviewable step
  before the rest of the route changes land.
