# Sportmonks — knowledge log

Append-only, one dated section per day of work. Never edit a previous day's
entry — add a new dated section at the bottom instead, even to correct
something (note the correction and link back).

---

## 2026-07-23

### Auth & plans
- Auth via query param `?api_token=...` (also supports an `Authorization`
  header, we used the query param throughout).
- Plan tiers (calls/entity/hour): Starter 2000, Growth 2500, Pro 3000,
  Enterprise 5000 (+ a temporary burst buffer on Enterprise only).
- 14-day free trial on every paid tier, credit card required, **one trial
  per account ever** — don't start the clock until tooling is ready.
- Free tier's actual league access is far narrower than advertised
  ("2200+ leagues" is the catalog, not what any given plan exposes): our
  free plan only ever showed 4 leagues (Danish Superliga, Scottish
  Premiership, and their playoff variants).

### Rate limiting — per entity, per rolling hour
- Limit is **per entity** (Fixture, Team, Player, League, Season, core
  Type each have their own separate hourly bucket) — exhausting one
  doesn't affect the others.
- The window is **rolling from your first request to that entity**, not a
  fixed clock hour — resets exactly 1 hour after that first call.
- This is a genuine hourly bucket, **not a burst/concurrency cap** as far
  as we could tell — running 3-4 concurrent requests via
  `ThreadPoolExecutor` caused no problems by itself.
- Confirmed for real: exhausted the Player-entity budget across two
  cumulative script runs and got a clean `429` with
  `Retry-After: 850` (~14 min) — waited it out, resumed normally once the
  window rolled over. The retry-after value is authoritative; just sleep
  for it.
- `GET /core/my/usage` reportedly returns live usage across *all*
  entities in one call (found in their docs, not yet used by our
  scripts) — worth using as a pre-flight check before a big run.

### Out-of-plan access is SILENT — this is the single biggest gotcha
- Requesting a league, team, or player **outside your plan does not
  return 403**. It returns a clean `HTTP 200` with `data: null` /
  `data: []`.
- Confirmed at three levels independently: leagues (`/leagues/{id}`),
  teams (`/teams/{id}`), players (`/players/{id}`) — all exhibit the
  identical pattern.
- Consequence: there is **no way to programmatically distinguish**
  "genuinely no data for this id" from "this id exists but isn't in your
  plan" using the API alone. Any code that only checks `status != 200`
  will silently misclassify out-of-plan gaps as real absence of data.
  Always check for empty/null `data` explicitly, and if the distinction
  matters, cross-reference against what you know is actually in your plan.
- `/leagues` (the bulk list) itself is subscription-filtered — it only
  ever returns leagues you've selected, not the full catalog. There is
  **no coverage-flag or coverage endpoint anywhere in the API** — unlike
  API-Football's `coverage.injuries`, Sportmonks give no way to ask
  "what could I get if I paid for league X" via the API. We had to scrape
  their public marketing coverage page instead to get any signal for
  leagues outside our plan, and even that page doesn't track injury
  coverage specifically (closest proxy: player-stat feature flags).

### Injury/absence data model (`sidelined`)
- No dedicated bulk injuries endpoint. `/sidelined` and
  `/sidelined/latest` both 404 — injuries only exist as an **include** on
  `/fixtures/*`, `/teams/{id}`, or `/players/{id}`.
- The `sidelined` array on a fixture is a **pivot/join row**:
  `{id, fixture_id, sideline_id, participant_id, player_id, type_id}`.
  The outer `player_id`/`type_id` are frequently null — don't rely on them.
- The real data lives in the **nested `sideline` object**, only present if
  you explicitly request `include=sidelined.sideline` (further nest
  `.player`/`.type` for name resolution — in practice those two
  sub-includes came back null for us regardless, so player/type names had
  to be resolved separately by id anyway).
- Nested `sideline` fields: `id, player_id, type_id, category` ("injury"
  or "suspended"), `team_id, season_id` (often null even for a record that
  clearly belongs to a specific season), `start_date, end_date` (null =
  still ongoing), `games_missed` (int), `completed` (bool).
- **Critical counting gotcha**: one real injury/suspension (one
  `sideline_id`) appears as a *separate pivot row in every fixture the
  player missed during that absence*. A single 7-game suspension can
  appear 4+ times across 4 different cached fixture files. Raw
  `sidelined` array length therefore counts **fixture-appearances**, not
  distinct injuries — a volume/activity proxy, not a true injury count.
  To get a real unique-injury count, deduplicate by `sideline_id`.

### History depth — real, but only via the right query path
- The **team-level** `sidelined` include only ever returns **currently
  open/active** absences — querying it made it look like there was no
  historical archive at all.
- The **actual archive lives behind `/fixtures/between/{d1}/{d2}`** with
  `filters=fixtureLeagues:{id}&include=sidelined.sideline` — querying old
  date windows this way returned real, complete, closed injury records
  going back to at least **October 2014** (verified: a specific 2014
  injury resolved with accurate `start_date`, `end_date`, `games_missed`,
  `completed: true`). Don't conclude "no history" from the team-level
  include alone.

### Pagination
- List endpoints (`/fixtures/between`, others) **do paginate**, and the
  default page size is smaller than expected and not clearly documented.
  A single busy league/month can exceed a default page and silently
  truncate if you don't paginate explicitly.
- Always pass an explicit `per_page` (we used 100) and follow
  `pagination.has_more` until exhausted. This bit us once — an early
  version of our sweep script under-counted before we added this.
- Confirmed working filter: `filters=fixtureLeagues:{id}` scopes a
  fixture date-range query to one league.

### Batch/multi-id lookups — inconsistent across entities
- Sportmonks' own rate-limit docs advertise a path-based batch endpoint,
  e.g. `GET /fixtures/multi/123,456,789`, counted as **one** request
  regardless of how many ids — confirmed documented for the Fixture
  entity specifically.
- We tested the same `/multi/{ids}` pattern for `/players` and `/teams`
  and it returned nothing usable both times — the pattern does **not**
  generalize to those entities. A `filters=id:1,2,3` query-param variant
  was tried first and also failed. Per-id fetching is the only reliable
  path for Player/Team right now.
- Lesson: **probe with one small batch before committing to it** for any
  new entity — we built this probe-then-fallback pattern into
  `sm_resolve_entities.py` after an early version blindly looped through
  537 sequential batch attempts with zero progress output, which looked
  like a hang but was actually just silently failing 537 times.

### Reference-data taxonomy gaps
- `/core/types` (the bulk paginated type taxonomy) does **not** contain
  every `type_id` that actually shows up in real `sidelined` records.
  Confirmed: the bulk list topped out at id 595 (375 entries total, with
  gaps even in that range), while real referenced type ids go past 2000.
- However, **direct single-id lookup does resolve ids missing from the
  bulk list** — confirmed via probe (ids 598, 600 resolved to "Muscular
  problems" / "Dead Leg" via `GET /core/types/{id}` despite being absent
  from the list response). Strategy: fetch the bulk list once (cheap),
  then fall back to per-id lookup for anything referenced-but-missing,
  and persist the newly-resolved ones back into the cache so a re-run
  doesn't repeat the work.

### Seasons
- `GET /leagues/{id}?include=seasons` returns a league's full season list
  (id, name, `is_current`) in one call — 53 calls total for all our
  leagues, cheap. Confirmed field names: `id`, `name`, `is_current`.
- We did **not** find explicit season start/end date fields under several
  candidate names (`starting_at`, `ending_at`, `start_date`, `end_date`,
  `started_at`, `finished_at`) — real season date boundaries may not be
  exposed this way, or use a field name we haven't found yet. Check
  `sm_resolve_seasons.py`'s output/cache before assuming this is solved.

### Practical takeaways for future scripts against this API
1. Always check for `data: null`/empty on 200, not just status code.
2. Always paginate explicitly with a generous `per_page`.
3. Probe any batch/multi endpoint with one small call before trusting it.
4. Cache every raw response to disk, keyed by exactly what was queried —
   this API's plan-gating and quota limits make re-fetching expensive or
   impossible once a trial ends; a local cache is the only durable record.
5. Concurrency (3-4 requests in flight) has caused no observed problems
   distinct from the documented hourly-bucket limit — treat concurrency
   and total hourly volume as separate concerns.

### Reference-file bug: wrong league ids silently poisoned 2 countries' data
- `data/sportmonks_coverage_uefa55.json` (our own reference file, scraped
  from Sportmonks' public coverage page early in this project) had wrong
  ids for Georgia (316 = "Erovnuli Liga 2", the 2nd tier) and Gibraltar
  (1526 = "Gibraltar Cup", a cup not the league). These were flagged as
  wrong when we corrected the league picker in MySportmonks, but the JSON
  file itself was never updated to match — so every script reading league
  ids from it (sweep, entity resolution, seasons) kept silently querying
  the wrong, unsubscribed competition for these two countries. Because
  wrong/out-of-plan ids return a clean `200` + empty data (see above),
  this produced no errors — it just looked like "no coverage" for two
  countries that actually had real data under a different id.
- Found by symptom: `sm_resolve_seasons.py` printed `-> HTTP 200 (cache)`
  instead of `-> N seasons` for exactly these two countries — the tell
  that `data` came back empty despite a 200.
- Fixed by querying `/leagues` directly, filtering to `country in
  (Georgia, Gibraltar)`, and reading off the ids actually in-plan:
  Georgia -> **319** ("Crystalbet Erovnuli Liga"), Gibraltar -> **1709**
  ("Premier Division"). Updated the JSON, then re-ran the sweep /
  seasons / entities scripts — caching meant only these 2 leagues needed
  fresh calls, everything else was skipped.
- **Lesson**: a `note` field flagging "this might be wrong" in a
  reference file is not the same as fixing it. If a script silently
  works around a known-bad value (e.g. by manually re-picking the right
  league in a UI elsewhere), the underlying data file needs to be
  corrected too, or every downstream consumer keeps inheriting the bug.

### Real measured 53-league breadth (post Georgia/Gibraltar fix)
- Full monthly sweep (36 months, all 53 leagues) tiered on the latest
  ~12-month bucket, same thresholds as the API-Football report: **13
  rich, 29 moderate, 9 thin, 2 token, 0 dark**. Every single one of the
  53 resolvable leagues has *some* injury data — a much better breadth
  picture than the earlier marketing-page-proxy estimate (which had
  guessed a ceiling around 35/53). That proxy was a reasonable use of
  the only signal the API itself couldn't provide (see the "out-of-plan
  gating" section above for why) — but it clearly underestimated real
  coverage once actually measured.

### Open question: does the TRIAL restrict historical depth vs a paid plan?
- Looking at all 3 year-buckets per league (not just latest), the
  pattern is stark: the oldest bucket (2023-08..2024-07) is dark or
  near-empty for almost every league, while the two most recent years
  are consistently rich. Taken alone this would mean "~2 years of real
  depth," mirroring what we found for API-Football.
- **But this contradicts an earlier, independently-verified result**:
  `sm_deep.py` proved, on the free tier, that this exact same query
  (Denmark, league 271, window 2024-03-01..2024-04-01, same endpoint/
  filter/include) returned 71 real sidelined records. Re-testing the
  identical query live, right now, on the Pro trial returns `data: []`
  with the message *"No result(s) found matching your request. Either
  the query did not return any results or you don't have access to it
  via your current subscription."* Reproducible, not a one-off glitch
  (re-tested fresh, bypassing cache).
- Working theory: **the trial period itself restricts historical fixture
  depth, separately from which leagues are in-plan** — plausible as a
  deliberate anti-abuse measure (the free tier is narrow but not
  time-boxed, so unlimited history there is low-risk; the 14-day Pro
  trial is broad — 120 leagues — and exactly the situation where
  someone could bulk-harvest years of history and cancel before
  billing). Unconfirmed — this is a hypothesis, not a proven fact.
- **Consequence if true**: the "only ~2 years deep" conclusion from this
  sweep may be a trial artifact, not Sportmonks' real capability. A paid
  (non-trial) Pro subscription might unlock the same depth we already
  proved exists for Denmark/Scotland on the free tier.
- **TODO, not yet sent**: email Sportmonks support asking directly
  whether the trial restricts historical fixture data depth compared to
  a paid Pro subscription, for leagues already reachable on the free
  tier. Recover this thread before drawing a final conclusion on
  Sportmonks' true historical depth — don't treat the current tiering as
  final until this is answered or tested on a real paid month.

### Free enrichment: entity records carry far more than a name
- Cached `/players/{id}` records include `position_id`,
  `detailed_position_id`, `nationality_id`, `country_id`,
  `date_of_birth`, `height`, `weight` — all unused until now beyond
  `display_name`.
- **Positions resolve for free** — `position_id`/`detailed_position_id`
  are just another entry in the `/core/types` taxonomy we already cache
  (filter on `model_type == "position"`, e.g. id 25 = "Defender", 148 =
  "Centre Back"). No extra API calls needed at all.
- **`/core/countries` exists and works** — confirmed via a probe
  following the exact same fetch-once pattern as `/core/types` (this was
  a guess, not documented anywhere we'd read; it worked). One call
  (paginated, 238 total countries), resolves `nationality_id`/
  `country_id` on players and teams. 97.5% of resolved players got a
  nationality from this on the first run.
- Cached `/teams/{id}` records include `country_id`, `venue_id`,
  `founded`, `short_code`, `last_played_at` — `founded`/`short_code` are
  free extras; `venue_id` would need a further `/core/venues`-style
  lookup if ever wanted (not fetched, low relevance to injuries).
- General lesson worth remembering: **when an entity is already being
  fetched for one field (a name), check what else is in the full raw
  response before assuming enrichment needs a new API call.** Several of
  these fields cost nothing extra since we already cache the complete
  raw object per entity, not just the field we originally needed.

---

## 2026-07-26

### Plan is UEFA-only — confirmed by confederation probe
- Ran `scripts/sm_leagues_by_confederation.py` against the live Pro trial:
  **57 leagues visible total**, grouped by their country's continent —
  Europe 50, Asia 7.
- The "Asia 7" are **not** AFC access: they're transcontinental UEFA members
  whose *geographic* continent Sportmonks tags as Asia — Armenia, Azerbaijan,
  Georgia, Israel, Kazakhstan, Türkiye (top leagues) + an Azerbaijan play-off
  variant. Lesson: **continent is a proxy for confederation, not equal to
  it.** Grouping leagues by `country.continent_id` will mislabel these six.
- Net: exactly **one confederation (UEFA)** is in-plan. No CONMEBOL / CAF /
  AFC(proper) / CONCACAF / OFC on this subscription. Since `/leagues` is
  subscription-filtered (see 2026-07-23), this list IS the reachable
  fixture/match universe for the current token — getting other confederations
  requires adding those leagues to the plan, not a code change (the backfill
  is already league-id-driven).
- **57 in-plan vs the 53 top-tier leagues we backfill**: the ~4 surplus are
  play-off / variant sub-competitions (confirmed one: "Play-offs 1/2
  (Azerbaijan)"). These are normally already contained within the parent
  league's fixtures, so unlikely to hold *distinct* sidelined records — not
  yet verified.

### Scope decision
- **Staying UEFA-only.** Focus on maximising the UEFA data we can already
  reach (historical fixture backfill toward 2014) rather than chasing
  confederations that need a paid plan expansion.
