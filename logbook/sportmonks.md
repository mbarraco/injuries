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

---

## 2026-07-27

### Subscription upgraded: 57 → 62 visible leagues
- Re-ran `scripts/sm_leagues_by_confederation.py` after the upgrade: **62
  leagues visible** (Europe 55, "Asia" 7 — same transcontinental caveat as
  2026-07-26). Still exactly one confederation: UEFA.

### The backfill was blind to 9 in-plan leagues — including all UEFA club competitions
- **`ingest/backfill.py` never asked the API which leagues exist.** It reads a
  hand-maintained reference file (`data/sportmonks_coverage_uefa55.json`,
  scraped from the public coverage page on 2026-07-23) listing 53 *domestic*
  leagues. So it happily reported `fetched=0 cached=151` for every league —
  true, and completely misleading. It had backfilled everything *in its list*,
  and the list was stale.
- Consequence: **Champions League, Europa League, Conference League and UEFA
  Super Cup had never been downloaded at all.** Not a quota problem, not an
  access problem — they were simply never asked for. Four of the nine missing
  ids predate the upgrade; they were in-plan and invisible the whole time.
- **Lesson: a static reference list is a silent single point of failure.** Any
  "nothing to fetch" result is only as trustworthy as the list it iterates.
  Diff against the source of truth, don't assume the list is current.
- Fix: `scripts/sm_find_missing_leagues.py` fetches `/leagues`, diffs it
  against the reference file, prints the gap, and caches the full list to
  `data/raw/sportmonks/leagues.json` (one League-bucket call, effectively
  free). Run it after any plan change — and periodically regardless.

### What the UEFA club competitions actually contain
| competition | id | non-empty months | fixtures | sidelined rows | span |
|---|---|---|---|---|---|
| Europa League | 5 | 126 | 4,553 | 11,796 | 2014–2026 |
| Champions League | 2 | 133 | 2,853 | 11,146 | 2014–2026 |
| Europa Conference League | 2286 | 49 | 2,269 | 7,003 | 2021–2026 |
| UEFA Super Cup | 1328 | 12 | 12 | 20 | 2014–2025 |

- Conference League starting at 2021 is correct — the competition didn't exist
  before then. A "gap" that matches real-world history is not a data gap.
- Dataset after backfill + enrich: **25,890 distinct absences (18,380
  injuries)**, up from 16,770. Fixture-months 8,003 → 9,362, non-empty
  1,116 → 1,454 (all enriched to the rich include bundle). Players cached
  10,737 → 13,130.

### Correction to 2026-07-26: play-off variants DO hold distinct absences
- That entry guessed the surplus in-plan leagues were "play-off / variant
  sub-competitions … normally already contained within the parent league's
  fixtures, so unlikely to hold *distinct* sidelined records — not yet
  verified." **Now verified, and the guess was wrong.**
- Belgium's UEFA Europa League Play-offs (id 1371) alone carries 192 fixtures
  and 152 sidelined rows. Russia's (495), Ukraine's (1691), Andorra's (1902)
  and Azerbaijan's (3570) are small but non-zero fixture-wise.
- The bigger error in that entry was assuming the surplus was *only* play-off
  variants. It also contained the four UEFA club competitions above. **Don't
  characterise an unexamined set by its most boring plausible member.**

### Correction: the "19,533 unknown-category rows" never existed
- Earlier work (and the expansion design doc) recorded a large `unknown`
  category — 19,533 rows then, 22,686 now — treated as a possible vendor
  data-quality problem.
- **It's a counting artefact, not missing data.** The feed repeats an absence
  once per missed fixture, and on many repeats the nested `sideline` object
  isn't populated. Tally categories per *pivot row* and those repeats show up
  as `unknown`; tally per distinct `sideline_id` (what the ETL loads) and
  **zero** absences are uncategorised — 18,380 injury + 7,430 suspended + 58
  suspension + 22 doubtful = 25,890 exactly.
- `scripts/sm_dataset_consistency.py` now reports both, clearly labelled, and
  only warns on distinct-absence unknowns. The design doc carries a correction
  note. The category-preserving `absence` schema is still right — the
  *suspension* half of that gap was real.
- **Lesson: state the unit before the number.** "22,686 unknown" was true of
  pivot rows and false of absences, and only the second reading was alarming.

### Out-of-plan silence, confirmed again at the qualifying-round boundary
- Entity resolution fetched all 243 previously-missing teams; **resolved count
  did not move** (866/1,109). Every one returned the usual clean 200 + empty
  `data`.
- Cause: UCL/UEL/UECL qualifying rounds pull in clubs from associations and
  divisions outside the 62 in-plan leagues. Orphan teams therefore rose
  178 → 244 (22%). Expected, not a defect — but note it means **continental
  competitions structurally guarantee orphan entities**, and the orphan rate
  is not a quality metric you can drive to zero.
- Orphan players went the other way, 52 → 21, since the new competitions
  resolved players the domestic-only pass had referenced but never fetched.

### Season access is the real cap on history — and it differs wildly by competition
- Measured live with `scripts/sm_check_season_depth.py`
  (`/leagues/{id}?include=seasons`, one League-bucket call each):

  | competition | seasons exposed | earliest |
  |---|---|---|
  | Champions League (2) | 27 | 2000 |
  | Europa League (5) | 27 | 2000 |
  | UEFA Super Cup (1328) | 22 | 2005 |
  | Europa Conference League (2286) | 6 | 2021 (competition founded then) |
  | **all 58 domestic leagues** | **3** | **2024** |

- **Domestic leagues expose exactly 3 seasons (2024/25–2026/27).** That is why
  the fixture cache held ~zero domestic data before 2024 — England's Premier
  League had 0 fixtures for 2014–2023. `/fixtures/between` can only return
  fixtures from in-plan seasons, so old windows come back legitimately empty.
  **Not a bug, not a query-path problem** (the backfill already uses the path
  verified on 2026-07-23), and **not fixable by more fetching.**
- This settles the 2026-07-23 open question "does the TRIAL restrict historical
  depth vs a paid plan?" — **yes, via season access**, and it's severe for
  domestic competitions.
- Corollary: the `(2014-2026)` spans printed by the inventory script are
  min..max of years holding *any* data, **not continuous coverage**. Easy to
  misread as depth we don't have.
- Added `--leagues` to `ingest/backfill.py`. Season depth varies so much that a
  blanket deep `--since` would spend ~8,900 calls on domestic windows that
  provably cannot contain data.

### Sidelined coverage ramps hard over time — DO NOT compare injury rates across years
- Backfilled the cups to 2000 (`--since 2000-01 --until 2013-12 --leagues
  2,5,1328`, 504 calls). Got **8,450 fixtures but only 1,155 sidelined rows**,
  vs 22,962 rows from the 7,418 fixtures of 2014–2026.
- Sidelined rows per fixture, UEFA cups, by year:

  | 2000–05 | 2006 | 2009 | 2011 | 2014 | 2017 | 2020 | 2023 | 2025 | 2026 |
  |---|---|---|---|---|---|---|---|---|---|
  | 0.00 | 0.00 | 0.10 | 0.31 | 0.76 | 1.71 | 3.23 | 3.29 | 6.88 | 7.97 |

- **Zero injury records exist before 2006**, and the density climbs ~monotonic
  for 20 years. This is Sportmonks' historical coverage improving, **not a
  real-world injury trend.**
- **This is the single most important analytical caveat in the dataset.** A
  naive "injuries per season over time" chart would show a dramatic rise that
  is entirely an artefact. Any longitudinal analysis must either restrict to
  recent years (2020+ looks plausibly stable-ish) or explicitly normalise by
  per-year coverage. Pre-2014 cup data is useful for *match context*, close to
  worthless for *injury* work.
- Now recorded as `coverage_<year>` rows in `data_quality` (one per year,
  written by `app/etl.py`) so the ramp is visible from the database itself, not
  only from this log. **Over all competitions** the series is flatter than the
  cups-only figures above — 0.00 (2000–06) → 0.76 (2014) → 3.23 (2020) → 3.93
  (2026) — because it changes composition: pre-2024 is cups only (domestic
  seasons don't exist in our data), 2024+ is cups plus 58 domestic leagues,
  which run a lower density. **The 2023→2024 step therefore mixes a coverage
  change with a competition-mix change** — don't read it as either alone. For a
  like-for-like trend, filter to one competition.

### Player-level `sidelined` does not exist — fixtures are the ONLY absence source
- `/players/{id}?include=sidelined` → **HTTP 404, "The requested include
  'sidelined' does not exist on Player"**. Same for `sidelined.sideline`.
- Corrects an earlier assumption in this project that a player-level sidelined
  include was available and merely untested for depth. It isn't available at
  all. (`sidelined.sideline` is valid on **fixtures**, where `sidelined` is a
  pivot wrapping a `sideline` object — that nesting is fixture-specific.)
- Combined with the 2026-07-23 finding that the **team-level** include returns
  only currently-open absences, this means: **every historical absence must be
  reconstructed from `/fixtures/between`.** There is no alternate route, so
  absence history is hard-capped by fixture/season access above.
- Lesson for probes: a 404 saying "include does not exist" is a *schema* fact,
  not a missing-data fact — worth reading the message rather than treating any
  non-200 as "no data". An earlier version of the probe script printed a
  confident "don't bother" verdict after all 5 requests 404'd; it now refuses
  to conclude anything when nothing succeeded.

### Open question: is the hourly bucket actually 5,000, not 3,000?
- Observed `remaining` values across runs: fixture 4,414, player 4,977 /
  4,520 / 2,585, team 4,822 / 4,757 — all well above the **3,000** this log
  recorded for Pro on 2026-07-23, and consistent with the **5,000**
  Enterprise figure.
- Note the player 4,520 reading predates the 2026-07-27 upgrade, so this is
  **not** simply an effect of the new plan.
- Unresolved: either the tier mapping in the 2026-07-23 table is wrong, or the
  trial grants a higher ceiling than the nominal tier. `GET /core/my/usage`
  (noted 2026-07-23, still unused) would settle it. Treat the 3,000 figure as
  unverified rather than authoritative when sizing runs.
