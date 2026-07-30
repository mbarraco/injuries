# API-Football — knowledge log

Append-only, one dated section per day of work. Never edit a previous day's
entry — add a new dated section at the bottom instead, even to correct
something (note the correction and link back).

Same discipline as `logbook/sportmonks.md`. Measured facts with dates live
here; `AGENTS.md` stays free of them.

---

## 2026-07-23 — feasibility probe (free tier)

Measured by `probe.py` at the repo root (runs 5–7, logs in `logs/`), before any
ingestion work existed. All figures below are from the free tier unless noted.

### Auth & transport
- Base URL `https://v3.football.api-sports.io`. Auth is a **request header**,
  `x-apisports-key: <key>` — not a query parameter.
- Also resold via RapidAPI with different headers; we use the direct
  (api-sports.io) form throughout.
- Version served is **v3** (their docs showed build 3.9.3 at the time). The
  `v3.` host always serves the latest 3.x — **a patch version cannot be
  pinned**, and responses carry no version field, so "which build answered
  this" is not recoverable from our logs.

### Rate limiting — global, not per-entity
- Free tier: **100 requests/day** and **~10 requests/minute**. Unlike
  Sportmonks there are no per-entity buckets — one global quota.
- Reported in response **headers**, not the body:
  `x-ratelimit-requests-remaining` / `-limit` (daily) and
  `X-RateLimit-Remaining` / `-Limit` (per-minute).
- Confirmed by hitting it: 2s pacing (30/min) tripped the per-minute cap and
  produced errors mid-run; **7s pacing (~8.5/min) ran clean** with zero 429s
  across a 55-league sweep.

### Empty vs blocked is distinguishable — unlike Sportmonks
- An out-of-plan season returns HTTP 200 with a **non-empty `errors`** object
  (we surfaced it as `plan✗`), while a genuinely empty result returns
  `{"errors": [], "results": 0, "response": []}`.
- Verified on Belgium (league 144, season 2024): clean `200`, `errors: []`,
  `results: 0` — i.e. **real absence of data**, not plan gating.
- This is a meaningful advantage over Sportmonks, where out-of-plan and
  no-data are indistinguishable (see `logbook/sportmonks.md`, 2026-07-23).

### `coverage.injuries` — an authoritative coverage flag, and it is accurate
- `GET /leagues` returns every league with a `seasons[]` array, each season
  carrying a `coverage` object including a boolean **`injuries`**.
- **One call answers "which leagues have injury data"** for the entire
  catalogue. Sportmonks has no equivalent at all.
- **Validated, not assumed:** run 6 read the flags; run 7 then called
  `/injuries` for real on 10 sampled leagues for 2024. The counts matched the
  flags exactly — data for ENG/ESP/GER/ITA/FRA, `0` for Andorra, San Marino,
  Malta, Faroe, Gibraltar. No false positives or negatives in the sample.

### Measured UEFA-55 injury coverage (flag-derived, seasons 2023/24/25)
- **43 of 55** UEFA top-tier leagues carry injury coverage for the 2025 season.
- **12 are dark in every season**: Albania, Andorra, Belarus, Faroe Islands,
  Gibraltar, Hungary, Iceland, Kosovo, Malta, Montenegro, San Marino, Serbia.
  (Liechtenstein has no domestic league — it does not resolve at all.)
- **History is far narrower than breadth.** Only **11 leagues** show coverage
  for 2023 *and* 2024: England, Spain, Germany, Italy, France, Netherlands,
  Denmark, Norway, Sweden, Russia, Türkiye. The other ~32 covered leagues
  appear to switch on at **2025**.
- Real 2024 record counts on the deep leagues: ENG 3,168 · ITA 3,036 ·
  GER 2,638 · FRA 2,460 · ESP 2,424 · DEN 949.
- **Unverified:** the 2025 flags were never count-confirmed — the free tier
  returns `plan✗` for the current season. The flag was perfect for 2023/24, so
  it is credible, but "43 leagues" remains a flag reading, not a measurement.

### League resolution gotchas (cost us two wrong runs)
- Matching a league by country + a substring name hint silently picks **second
  divisions**: `"Erovnuli"` matched Georgia's *Erovnuli Liga 2*, `"Lyga"`
  matched Lithuania's *1 Lyga*, and Malta/Faroe resolved to their 2nd tiers.
- Fixed by preferring an **exact normalised name match** before falling back to
  substring. Same class of bug as the Sportmonks Georgia/Gibraltar league-id
  error — **a plausible-looking id is not a verified one.**
- A name-only match with no country check is worse still: three different
  countries all resolved to Scotland's *Premiership* (id 501) in an early
  Sportmonks-side run, producing real records attributed to the wrong nations.
  Country match must be mandatory, never a fallback.

### Known gap in the injury record itself
- Per the vendor's own catalog, `/injuries` carries **no recovery date, no
  severity, no medical diagnosis** — only player, team, fixture, league and a
  reason string.
- Sportmonks' `sideline` object *does* carry `start_date`, `end_date`,
  `games_missed`, `completed`. So the two vendors trade off: **API-Football is
  wider, Sportmonks is deeper.** Neither supersedes the other.

### Open questions for the paid plan
1. Does `/status` confirm the Pro daily limit and per-minute cap? (All figures
   above are free-tier headers plus the published plan table.)
2. Do the 43 leagues flagged for 2025 actually return records?
3. **Does API-Football expose domestic seasons older than 2024?** This is the
   one that matters — Sportmonks' domestic history is hard-capped at 3 seasons
   (`logbook/sportmonks.md`, 2026-07-27), so if API-Football is also shallow,
   it adds breadth and a cross-check but **not history**.

---

## 2026-07-29 — Phase 0 recon on the paid Pro plan

Measured by `scripts/apifootball/af_status_and_coverage.py` (two calls:
`/status`, `/leagues`). Answers all three open questions above.

### Plan limits — confirmed authoritative, and higher than the free-tier guess
- `GET /status` reports plan **Pro**, active, ending 2026-08-23.
- **7,500 requests/day** and **300 requests/minute** (headers
  `x-ratelimit-requests-limit` = 7500, `X-RateLimit-Limit` = 300).
- The per-minute ceiling is **30x the free tier's 10/min**, which changes
  pacing entirely: the 7s spacing that free tier required is unnecessary here.
  Concurrency is worth using for the Phase 2/3 runners.
- `/status` itself does **not** count against the daily quota in an obvious way
  — after two calls the counter read 7,498/7,500, i.e. both were billed.

### ANSWERED: API-Football exposes real pre-2024 domestic history
- **This is the headline, and it reverses the 2026-07-23 expectation.** That
  probe sampled only seasons 2023/24/25 and concluded ~32 leagues "start at
  2025". Reading the *full* season list per league shows coverage reaching back
  to **2020** for the major leagues.
- Injury coverage by season (count of UEFA top-tier leagues):

  | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---|---|---|---|---|---|---|
  | 11 | 12 | 11 | 11 | 11 | **43** | 4 |

- **Eleven leagues carry 6–7 seasons** (2020–2025/26): England, Spain, Germany,
  Italy, France, Netherlands, Denmark, Norway, Sweden, Russia (7), Türkiye.
- **Sportmonks structurally cannot provide this.** Its domestic seasons are
  capped at 3 (2024/25+) and no amount of fetching or paying on that plan
  changes it. So API-Football is **not** merely a breadth play or a
  cross-check — for these 11 leagues it is *the only route to 2020–2023
  domestic injury history this project has*.
- The 2026 row (Denmark, Norway, Russia, Sweden) is not an anomaly: those are
  calendar-year season leagues, so their "2026" season is the current one.

### Coverage is non-contiguous, and a range display hid it
- Austria, Belgium and Portugal have coverage in the 2020–2025 *span* but only
  **2, 3 and 2 seasons** in it respectively — gaps in between.
- The first version of the report rendered these as `2020..2025 (2)`, which
  reads as a six-season range. Fixed to collapse to a range **only when the
  years are genuinely contiguous**, and list them explicitly otherwise.
- **Lesson, same shape as the Sportmonks "22,686 unknown" artefact:** a summary
  that is technically true (min, max, count) can still assert coverage that
  isn't there. State the unit, and don't let a formatter imply contiguity.

### Breadth, re-measured
- **43 of 54** resolved UEFA top-tier leagues have injury data in at least one
  season — matching the 2026-07-23 flag reading exactly.
- **11 dark in every season**: Albania, Andorra, Belarus, Faroe Islands,
  Gibraltar, Hungary, Iceland, Kosovo, Malta, Montenegro, Serbia.
- **Correction to 2026-07-23**, which listed 12 dark including **San Marino**.
  San Marino now shows 2025 coverage. Either coverage was added in the interim
  or the earlier three-season sample missed it — cannot distinguish from here.
  Either way it confirms **coverage is a moving target**; re-run this recon
  periodically rather than trusting a cached list.
- Liechtenstein does not resolve — it has no domestic league. Expected.

### Real cost of the ingestion plan, from measured data
- Total (league, season) pairs with injury coverage: **103**.
- So the injuries spine is **~103 calls**, not the ~130 estimated from the
  three-season assumption. Fixtures, standings and teams add ~103 each;
  `teams/statistics` is the ~2,000-call tail.
- **Whole spine + aggregates ≈ 2,600 calls — about a third of one day's Pro
  quota.** The plan's cost concern was overstated; runtime is not the
  constraint.

### `/injuries` rejects the `page` parameter
- Sending `page=1` returns HTTP 200 with
  `errors: {"page": "The Page field do not exist."}` and zero records.
- The endpoint still *reports* `paging: {current: 1, total: 1}` — it simply
  returns the whole result set in one response and refuses an explicit page
  field. England 2024 returns 3,168 rows in a single body.
- **API-Football's endpoints are not uniform in this.** Fix applied in
  `ingest/apifootball/client.get_all`: omit `page` on the first request, send
  it only from page 2. Non-paginating endpoints never see it; paginating ones
  are unaffected because page 1 is their default.
- Cost of finding this: 5 wasted calls, and a diagnosis that needed the
  response log because the runner reported a bare `error`. The runner now
  carries the vendor's message into its failure list.

### The record grain is PER-FIXTURE, not per-injury — no spell id exists
- Sample (`GET /injuries?fixture=686314`, Bayern–PSG, UCL 2020/21): 13 records,
  every one shaped
  `{player: {id, name, type, reason}, team: {...}, fixture: {...}, league: {..., season}}`.
- **`type` is `"Missing Fixture"`** — the record asserts "this player missed
  *this match*", not "this player had an injury from X to Y". A player out for
  eight matches yields **eight rows**.
- **Fields the record does NOT carry:** `start_date`, `end_date`,
  `games_missed`, `completed`, severity, diagnosis. Only a free-text `reason`
  ("Broken ankle", "Knee Injury", "Knock", "Illness", "Muscle Injury").
- **There is no absence/spell identifier.** This is the decisive difference
  from Sportmonks, whose `sideline_id` lets repeats collapse to one real spell
  deterministically (`logbook/sportmonks.md`, 2026-07-23). Here, reconstructing
  spells requires *inferring* them — grouping a player's consecutive missed
  fixtures by matching `reason` text — which is lossy and genuinely ambiguous
  when the same injury type recurs within a season.
- **Correction to this file's 2026-07-23 entry.** It recorded "real 2024 record
  counts … ENG 3,168 · ITA 3,036 · GER 2,638 · FRA 2,460 · ESP 2,424 · DEN
  949" and called them injury records. They are **player-fixture absence
  rows**, not injuries. The true injury count is unknown and strictly lower —
  by roughly the average number of matches missed per spell. Sportmonks'
  ~117,000 fixture-level mentions deduped to 26,408 real spells, a ~4.4x
  factor; if a similar ratio holds, ENG 2024's 3,168 rows are on the order of
  700 actual injuries. **Not measured — do not quote that estimate as data.**
- **Suspensions are mixed in**, same as Sportmonks: `reason: "Suspended"`
  appears alongside injuries. Any injury-only view must filter on `reason`.
- Consequence for the schema (slice 6): the vendor's grain is the *fixture
  appearance*. Store it faithfully at that grain, keep the raw `reason` and
  `type` strings, and treat spell reconstruction as a derived, clearly-labelled
  layer — never as if the vendor had supplied it.
- Still unknown: the full domain of `type` (only `"Missing Fixture"` observed;
  a "Questionable"/doubtful value plausibly exists) and of `reason`. Tally both
  across the real dataset once the spine is fetched.

### `/injuries` parameter surface — richer than the league&season path we use
Documented combinations (vendor docs, not yet all probed):

| query | use |
|---|---|
| `?league={id}&season={y}` | **the backfill path** — whole season in one call |
| `?date=YYYY-MM-DD` | **the sync path** — one call covers every league that day |
| `?fixture={id}` | single match |
| `?ids=1-2-3-…` | **batch by fixture id, dash-separated** |
| `?team={id}&season={y}` | one club's season |
| `?player={id}&season={y}` | one player's season |
| mixed, e.g. `?date=…&league=…`, `?league=…&season=…&team=…` | narrowing |

- **`?date=` is the right incremental-sync path**, and materially better than
  what the plan assumed. Topping up means one call per elapsed day across all
  leagues, rather than re-fetching 103 league-seasons. Sportmonks has no
  equivalent — its sync re-walks fixture windows per league.
- **`?player={id}&season={y}` exists**, unlike Sportmonks, where the
  player-level `sidelined` include returns HTTP 404 ("does not exist on
  Player", 2026-07-27). It does not solve the missing spell id — the rows are
  still per-fixture — but a player-scoped query is available if ever needed.
- `?ids=` uses **dash separation**, not commas. Probe before relying on it;
  Sportmonks' analogous `/multi/` batch worked for fixtures and silently failed
  for players and teams (2026-07-23).

### The UEFA club competitions are invisible to a country-matched work list
- UCL/UEL/UECL/Super Cup carry `country: "World"`, so any sweep that resolves
  leagues by UEFA member nation **structurally cannot see them** — it returns a
  complete-looking result with four major competitions missing.
- `af_status_and_coverage.py` originally had exactly this hole. Caught before
  any backfill ran, from a vendor doc example using `league=2` (Champions
  League) — not from the tooling, which reported 43/54 covered and looked
  healthy.
- **This is the same blind spot, in a new codebase, that
  `logbook/sportmonks.md` records on 2026-07-27** — where it hid ~30,000
  sidelined rows and the deepest history in that dataset behind a truthful
  "fetched=0 cached=151".
- Fixed by a second resolution pass matching the four competitions by name
  across the whole catalogue. Matched by **name, not hardcoded id**, so a
  rename surfaces as `unresolved` rather than silently dropping out.
- **Lesson, restated because it recurred:** the danger is not that a work list
  is wrong, it is that an incomplete one produces confident, well-formed
  output. Cross-check any list against the API's own catalogue before trusting
  a "nothing to fetch".

### Club competitions found: UCL and Europa League are as deep as the Big 5
After the name-matched pass, coverage went **43/54 → 47/58** resolved leagues:

| competition | id | injury seasons |
|---|---|---|
| UEFA Champions League | 2 | **2020–2025 (6)** |
| UEFA Europa League | 3 | **2020–2025 (6)** |
| UEFA Europa Conference League | 848 | 2025 |
| UEFA Super Cup | 531 | 2025 |

- The deep-history tier grew from 11 leagues to **13**. Work list: **117
  league-seasons**, up from 103.
- Mirrors the Sportmonks side, where the cups also hold the deepest history —
  though there the depth reaches 2000 and here it stops at 2020.

### VERIFIED: the `coverage.injuries` flag is accurate — 117/117, no exceptions
Full spine fetched 2026-07-29 (`python -m ingest.apifootball.injuries`):

- **117 of 117 flagged league-seasons returned real records.** Outcomes:
  112 `ok`, 5 already cached, **zero `EMPTY`, zero `PLAN_BLOCKED`, zero
  failures.**
- **This closes the open question carried since 2026-07-23.** The flag was
  validated for 2023/24 by sampling, but the 2025 seasons had never been
  count-confirmed (the free tier returns a plan error for the current season).
  They are now confirmed, on a paid plan, across every covered league.
- Practical consequence: **`/leagues` can be trusted as the work list.** One
  cached call plans the entire crawl, with no need to probe league-seasons
  speculatively to discover what exists. Sportmonks offers nothing equivalent —
  there, coverage had to be inferred by measurement.
- Cost: **112 calls, ~30 seconds**, 7,500 → 7,381 daily quota. The entire UEFA
  injury record for six seasons costs ~1.5% of one day's budget.

### Volume: 129,016 rows — and what they are not
- **129,016 player-fixture absence rows** across 117 league-seasons
  (~1,100 average, heavily skewed: the Big 5 and the two big cups dominate;
  the first five alphabetically averaged only ~196).
- **These are not 129,016 injuries.** Each row is one player missing one
  fixture (`type: "Missing Fixture"`), so a multi-match absence contributes one
  row per match — and there is no spell id to collapse them by.
- For scale, Sportmonks holds ~117,000 fixture-level mentions that dedupe to
  **26,408 distinct absences** (~4.4x). If a similar ratio held here the true
  figure would be ~29,000 — **but that ratio is borrowed, not measured, and
  must not be quoted as a finding.** Measure it directly from the cache before
  any claim about how many injuries this dataset contains.
- The two vendors are therefore closer in real volume than the raw row counts
  suggest, over different footprints: Sportmonks deeper in time (cups to 2000)
  and richer per record (dates, duration, spell id); API-Football wider in
  breadth (47 competitions) with thinner records.

### Measured grain (offline, `scripts/apifootball/af_measure_grain.py`)
129,016 rows · 10,298 players · 475 teams · 19,803 fixtures · 47 competitions.

**`type` has TWO values, and the second is not an absence:**

| type | rows | share |
|---|---|---|
| `Missing Fixture` | 112,298 | 87.0% |
| **`Questionable`** | **16,718** | **13.0%** |

- `Questionable` records a **doubt about availability**, not a missed match —
  the player may well have played. Treating the two alike inflates every
  absence count by ~13%. Corrects this file's 2026-07-29 entry, which recorded
  only `"Missing Fixture"` as observed.

**`reason` is free text with 205 distinct values**, mixing injuries with
disciplinary and administrative absences. Top: Injury 29,220 · Knee 25,187 ·
Muscle 13,476 · Ankle 6,781 · Thigh 6,465 · Yellow Cards 5,309 · Inactive
5,071 · Red Card 3,910. Note the most common value is the useless generic
`"Injury"` — body-part detail is present for many rows but not most.
Conservative substring split: **85.3% injury-ish (109,988) / 14.7% positively
non-injury (18,994)**. The injury figure is an *upper bound* — it is everything
not positively identified as something else, not a measurement.

**One absence spans several competitions — 14.8% of the time.** 4,203 of 28,327
`(player, reason)` groups touch more than one competition, because an injury
keeps a player out of his domestic league *and* his European cup. These are the
same absence seen through several league feeds. **Dedup must key on the player,
never the league**; a league-keyed count over-counts by ~15%, concentrated on
players at the biggest clubs — exactly the ones most analyses centre on.

**Spell reconstruction is NOT reliable — this is the decisive finding.** With
no spell id, absences can only be inferred by collapsing a player's consecutive
missed fixtures. Restricted to the 112,298 confirmed `Missing Fixture` rows
(`Questionable` excluded), the result depends heavily on the gap threshold:

| gap (days) | 7 | 14 | 30 | 60 | 120 |
|---|---|---|---|---|---|
| inferred absences | 57,164 | 40,735 | 35,879 | 34,420 | 32,617 |
| rows per absence | 2.0 | 2.8 | 3.1 | 3.3 | 3.4 |

- **75% spread.** The count nearly doubles across plausible thresholds, and no
  threshold is vendor-supported.
- At a 30-day threshold: **~35,900 inferred absences**, 3.1 rows each — same
  order as Sportmonks' 26,408 at 4.4 rows each, over a wider, shallower
  footprint. Quote the threshold whenever quoting the number.
- **Schema consequence (slice 6): store the fixture-appearance grain as the
  source of truth.** Any absence count is a derived view that must carry the
  threshold that produced it. Sportmonks' 26,408 is *measured* from a real
  `sideline_id`; any figure here is *estimated*. **They must never appear in
  the same column, or as comparable numbers, without that distinction.**

**Two measurement errors made and corrected in the same session**, recorded
because both produced confident, well-formed, wrong output:
1. Cross-competition duplication was first keyed on `(player, date)` and
   reported **0.0% — and the true figure is 14.8%.** A player cannot appear in
   two matches on one day, so that check could only ever return ~zero; it
   measured nothing while looking like a clean negative result. Re-keyed on
   `(player, reason)` spanning multiple leagues, which is the actual question.
   **A metric that cannot return a positive is worse than no metric**: it
   retires the question.
2. The non-injury classifier missed `Inactive` (5,071), `National selection`
   (963 — the marker read `national team`) and `Lacking Match Fitness` (540).
   Fixing it moved the split from 90.4%/9.6% to **85.3%/14.7%**. The figure was
   labelled an upper bound throughout, which is the only reason it was never
   misleading.
3. The first absence table also counted `Questionable` rows as absences,
   overstating every figure by ~13% (e.g. 39,958 vs 35,879 at a 30-day gap).

### Tiers 1–3 collected — everything except per-fixture detail
Fetched 2026-07-29 across two runs (`ingest.apifootball.crawl`):

| target | records | league-seasons | notes |
|---|---|---|---|
| injuries | 129,016 | 117 | 112 calls |
| fixtures | **32,238** | 117 | all `ok` |
| teams | 2,947 | 117 | team-seasons |
| standings | 115 | 117 | **2 empty** — Super Cup et al. have no table |
| players | **75,213** | 117 | 2 empty; paginated ~25 pages each |
| team statistics | 2,947 | — | one per team-season, all `ok` |

- Total spend for tiers 1–3: **~6,500 calls**, well inside one day (7,500).
  Day ended with 419 remaining.
- **19,803 of 32,238 fixtures (61%) carry at least one absence record.** A
  useful sanity signal: sparse or broken coverage would sit far lower.
- **`/players` is paginated (~25 calls per league-season)** — the only target
  here where one item is not one call. An early cost estimate treated it as 1
  and under-reported it ~25x. Now modelled explicitly via a `pages` field per
  target.
- **Resumability verified in the wild, not just in tests.** A run interrupted
  mid-`players` left 27 league-seasons cached; the next run detected them and
  fetched only the missing 90.
- Progress reporting had to be fixed twice for the same underlying reason: a
  fixed stride assumes one job is one call. With paginated jobs, a stride of 25
  meant ~2.5 minutes of silence, which reads as a hang — the exact failure
  `logbook/sportmonks.md` records for an early batch script (2026-07-23).
  Both crawlers now scale the stride to the work.

### Daily quota exhaustion was retried like a per-minute one — wasted 16 calls
- First `fixture_detail` run hit the real daily wall (420 `ok`, then
  `quota_exhausted`) and the client retried it 4 times with 10/20/40/60s
  backoff before giving up — a wait for a window that would not clear for
  hours, not seconds.
- Worse: the run's final `quota()` read `day_remaining: 7499` — a number from
  BEFORE the exhaustion. The daily 429's body carries **no rate-limit
  headers at all** (`quota: {}` in the log), so nothing ever corrected the
  stale reading. A crawl trusting that number would believe it had a full
  day's budget when it had none.
- The real body: `{"rateLimit": "Too many requests. You have reached your
  daily request limit. Please try again later or upgrade your plan."}` —
  named explicitly, distinguishable from a generic per-minute 429
  (`"Too many requests."` with no "daily" wording).
- Fixed: `classify()` now returns a separate `DAILY_EXHAUSTED` outcome by
  reading the body text, and `get()` returns it immediately with **no
  retry** and forces the client's `day_remaining` to 0 directly, since the
  headers cannot. Both crawlers stop on `DAILY_EXHAUSTED` exactly as they
  did on the old single `QUOTA_EXHAUSTED`.
- Progress reporting had the same "100% but nothing happened" bug as the
  stride issue above: counting stop-skipped items as done made an aborted
  run's final line read `32,238/32,238 · 100.0%` after fetching only 420.
  Fixed to track fetched-vs-skipped separately.

### Upgraded Pro -> Ultra: both ceilings scaled, confirmed via /status
- **75,000 requests/day** (was 7,500) and **450/minute** (was 300) — confirmed
  by re-running `af_status_and_coverage.py --refresh`, not assumed. The
  per-minute figure was worth checking explicitly: plan tiers commonly scale
  daily volume without touching the per-request-rate ceiling, since that is
  often an abuse control rather than a subscription entitlement. Here it moved
  too.
- Coverage re-checked in the same call: still 47/58, same dark list, San
  Marino still shows 2025. No drift since the 2026-07-29 measurement.
- **Revised tier-4 timeline.** Pacing (450/min x 0.8 safety margin) is now
  ~360/min sustained, ~6/s — and at that rate the PER-MINUTE pacing, not the
  daily budget, is the binding constraint for the smaller job:
  - `players` only (~32,000 calls): ~32,000 / 75,000 fits in one day's quota
    with room to spare, and at ~6/s the wall-clock pacing time is ~1.5 hours.
  - all four endpoints (~129,000 calls): exceeds one day's 75,000 quota, so
    it spans two calendar days — the daily budget is spent, the run stops
    cleanly, resumes the next day for the remainder. Total ACTUAL fetching
    time is still only ~6 hours of pacing, just split across the quota reset.
    Down from an estimated 17 days on the Pro tier.
- Net effect: the earlier "players first, statistics last" sequencing to
  conserve scarce daily quota matters much less now — the binding constraint
  shifted from days of daily-budget to hours of per-minute pacing. Running
  `--endpoints all` in one sitting is now reasonable where it previously
  was not.

---

## 2026-07-30

### CRAWL COMPLETE — all endpoints, all 47 competitions, 2020–2025
Finished on the Ultra plan. Everything the plan set out to collect is on disk.

| layer | unit | count | notes |
|---|---|---|---|
| injuries | league-season | 117 | **129,016** absence rows |
| fixtures | league-season | 117 | **32,238** fixtures |
| teams | league-season | 117 | 2,947 team-seasons |
| standings | league-season | 115 | 2 legitimately empty (no table) |
| players | league-season | 117 | ~**93,800** player-seasons after repair |
| team statistics | team-season | 2,947 | one call each |
| fixture players | fixture | **32,238** | 100% — the minutes source |
| fixture lineups | fixture | **32,238** | 100% |
| fixture events | fixture | **32,238** | 100% — **450,943** events |
| fixture statistics | fixture | **32,238** | 100% — 54,398 records |

- Per-fixture crawl cost **61,412 calls in one session** (~6 hours of pacing),
  finishing with 13,924 of 75,000 daily quota still unspent. The 17-day
  estimate from the Pro tier collapsed to a single day.
- `empty` outcomes are legitimate, not failures: 922 fixtures have no events
  and 5,038 no statistics — overwhelmingly future or unplayed fixtures in the
  current season. Exactly one hard `error` across 32,238 statistics calls.

### Truncation repair recovered ~18,500 player-seasons — in the biggest leagues
- The 16 truncated files held exactly 1,000 records each (50 pages x 20, the
  old `max_pages` ceiling). Re-fetched at 500 pages they hold **34,582** — so
  roughly **18,500 player-season records had been silently missing**.
- The affected competitions were La Liga, Serie A, the Premier League, Türkiye,
  Champions League and Europa League — i.e. the deepest, most-queried leagues.
  A truncated player list means a truncated **minutes denominator**, which
  *inflates* injury rates. Nothing would have errored; the rates would simply
  have been too high for the leagues most likely to be looked at.
- **`truncated: true` had been written faithfully into those cache files for
  hours and nothing ever read it.** The crawl reported `{'ok': 117}` throughout.
  Found only by a deliberate code review, not by any runtime signal.
- **Lesson: a recorded warning nobody reads is not a safeguard.** The value of
  `truncated` was zero until something surfaced it. `report_truncation()` now
  runs after every crawl and scans the whole cache, so the check applies to
  historical files too, not just the run that just finished.

### Rate-limit classification: three distinct wordings, all per-minute
Captured verbatim (see `logs/apifootball-crawl.20260729-142857.log`):

| status | message |
|---|---|
| 429 | "...reached your per-minute request limit ... or upgrade your **plan**" |
| 200 | "...exceeded the limit of requests per minute of your **subscription**" |
| 200 | "Your **rate limit** is 450 requests per minute." |

- **Neither keyword ordering works.** Two of the three mention plan/subscription
  as an upsell, so a plan-before-quota order misreads them as `PLAN_BLOCKED`
  (this happened, 8 times); a quota-before-plan order would misread genuine
  plan gating that mentions a limit. Rate limiting must be matched on its own
  distinctive phrasing (`too many requests`, `per-minute`, `rate limit`).
- All three are now pinned verbatim in `tests/test_apifootball.py` so a future
  reorder cannot silently undo the fix.

### Two crawler processes share one quota but pace independently
- Running `crawl` and `fixture_detail` simultaneously produced per-minute 429s
  with ~58,000 daily calls still available: each client paces to ~360/min on
  its own, so two together aim at ~720/min against a 450/min ceiling.
- **Operational rule: one crawler at a time**, or halve `--concurrency` on each.
  The pacer is per-process and cannot coordinate; fixing that properly would
  need a lockfile or shared counter, which is not worth it here.

### Database and app built: `apifootball.db` + `/af/*`
Schema `app/schema_af.sql`, ETL `app/etl_af.py`, queries `app/af_queries.py`,
routes `app/af_routes.py`, templates `app/templates/af/`.

**Loaded from the cache:**

| table | rows |
|---|---|
| af_absence | **129,016** |
| af_player_season | **98,246** |
| af_player | 33,750 |
| af_fixture | 32,238 |
| af_team | 845 |
| af_reason | 205 |
| af_league / af_league_season | 58 / 117 |

**Reason classification** (confirmed absences, `af_reason` mapping table):
injury 109,805 · suspension 10,896 · administrative 8,272 · **unknown 43**.
The unknown bucket is 34 blank strings plus 9 rows the vendor itself labels
`"other"` — genuinely unclassifiable, not a marker gap. The 85.1% injury share
independently reproduces the 85.3% upper bound measured offline from the raw
cache by `af_measure_grain.py`, via a completely different code path.

**Why the schema is NOT a copy of `schema.sql`** — each divergence is a measured
fact, not a style choice:
- no `absence.id` from a spell id (none exists) — PK is surrogate, grain is
  `(player, fixture)`
- no `start_date` / `end_date` / `duration_days` / `games_missed` /
  `is_ongoing`; the vendor supplies none of them
- `type` is new and load-bearing: `Missing Fixture` (112,298) vs
  `Questionable` (16,718). **Never summed.** `af_confirmed_absence` is the
  default population for every count.
- `reason` is free text (205 values), so `af_reason` is a mapping TABLE, not a
  type FK — inspectable and correctable without touching queries, which matters
  given the classifier was wrong twice before it was right.

**Two silent-failure guards the ETL enforces before writing anything:**
1. **Refuses to build if any cache file is flagged `truncated`**, with the fix
   command. A truncated /players file means a truncated minutes denominator,
   which *inflates* every rate. `--allow-truncated` is the escape hatch and
   records the fact in `af_data_quality`.
2. **Every distinct reason must have an `af_reason` row.** `af_injury` joins
   that table, so an unmapped reason vanishes from the view rather than
   surfacing as uncategorised. `af_unmapped_reason` makes any gap queryable and
   must be empty after a rebuild.

**Two expected, named invariant reports** (both vendor quirks, not code bugs):
- **39 orphan fixtures** (0.03%) — absences referencing a fixture absent from
  `af_fixture`, concentrated in Eredivisie 2025 (38) and Armenia 2025 (1).
  `/injuries` and `/fixtures` occasionally disagree about which matches exist
  in the current season.
- **120 orphan players** — injured badly enough to miss a whole season, so
  `/players` (which only returns players *with* statistics) never lists them.
  Their absences are kept and still counted in team/league rollups, but they
  have **no minutes denominator**, so their rate is undefined rather than zero.

**App layout decision: shared shell, separate domain.** A standalone
`app-api-football/` was rejected — it would have duplicated `auth.py`, `db.py`,
`macros.html`, `base.html` and ~19 near-identical templates, and `AGENTS.md` is
explicit that macros exist to keep behaviour identical across pages. Instead
`/af/*` is purely additive: its own query layer, its own read-only database
via `db.connect_af()`, its own `af/_macros.html` for `/af/`-prefixed entity
links, but the same auth, layout and shared macros. Nothing in the existing
Sportmonks routes, queries or `app.db` changed.

**Bugs caught writing the query layer, before they ever ran:**
- `player_detail` built and discarded an entire unfiltered `absence_list()`
  call — a real wasted query on every player page view.
- Its headline `total_absences` summed only the `(league, season)` pairs present
  in `af_player_season`, which would have **undercounted exactly the players
  whose season coverage is thinnest** — the same 120 with no stats rows. Now
  counted directly from `af_confirmed_absence`, with a regression test that
  inserts an absence in an unmapped season and asserts the total includes it.

**Test fixtures live in `tests/conftest.py`**: `af_db_path` (writable, before
any connection opens) and `af_connection` / `af_client` (read-only). The split
exists because `apifootball.db` is opened `mode=ro` like `app.db` — a test that
needs to add rows must write through its own connection first, which is also a
more honest simulation of rebuild-then-serve. A test that tried to mutate
through `af_connection` failed correctly; the fixture was right and the test
was wrong.

---

## 2026-07-30 — `/transfers` probed: 9 calls, 1,642 move rows

First contact with `/transfers`. Nothing in this repo had ever called it, so
every claim in `docs/football-api/transfers-endpoint.md` was unverified. Probed
read-only via `scripts/apifootball/af_probe_transfers.py` (writes nothing to
`data/raw/`): 6 well-travelled players, 2 large clubs (Ajax 194, Galatasaray
645), 1 pagination test. The measurements below come from the probe's own
response log, re-read from disk rather than re-fetched.

### It escapes the 2020–2025 cap. This is the finding that matters.

Every other endpoint on this vendor is hard-capped at 2020–2025. `/transfers`
is not:

| era | move rows in the 1,642-row sample |
|---|---|
| 1920s | 4 |
| 1990s | 4 |
| 2000s | 142 |
| 2010s | 695 |
| 2020s | 797 |

**51% of rows predate the window every other API-Football endpoint is limited
to.** Career history before 2020 is not obtainable from this vendor by any
other route. That alone justifies the crawl.

### `?team=` is club-scoped — measured, not assumed

Ajax: 704 move rows, **704 of 704 touch team 194**. Galatasaray: 866 of 866.
So the team form returns only moves in and out of that club, not the full
careers of the players involved. It does *not* substitute for a per-player
crawl if the goal is career reconstruction.

It is still worth running first, because it is absurdly cheap and *wider* than
our player dimension: one Ajax call returned **333 player envelopes** against
the **152** distinct players `af_player_season` holds for Ajax — 2.2x. Same for
Galatasaray (310 vs 144).

| crawl | calls | what it gets |
|---|---|---|
| per-team (`af_team`) | ~845 | every move in/out of our 845 clubs, all history, incl. players outside `af_player` |
| per-player (`af_player`) | ~33,750 | complete careers, incl. moves between two clubs we don't cover |

### `type` is a THREE-way mixed field

The doc predicted a small category vocabulary. It is worse: one column carries
a category, a fee, or a null-marker, and the fee has three formats.

Categories seen (12 distinct):

| value | rows | note |
|---|---|---|
| `Loan` | 483 | |
| `N/A` | 353 | **21% of all rows.** Not "no transfer" — often an unlabelled loan return |
| `Free` | 290 | |
| `Transfer` | 76 | paid, fee undisclosed |
| `Return from loan` | 53 | |
| `Free agent` | 45 | signed while unattached — arguably NOT the same as `Free` |
| `Back from Loan` | 28 | |
| `Free Transfer` | 11 | |
| `Raise` | 7 | |
| `-` | 5 | |
| `End of Loan` | 1 | |
| `Swap` | 1 | |

Three spellings of one concept: `Return from loan` / `Back from Loan` /
`End of Loan` (82 rows). Three of another: `Free` / `Free Transfer` /
`Free agent`. **Do not hard-code these** — it needs an `af_transfer_type`
mapping table with the same invariant as `af_reason`: every distinct raw value
gets a row, and the unmapped report must be empty after a rebuild.

Fees: **112 distinct strings, 289 rows (17.6%)**, in three formats —
`"€ 7M"` (281), `"1.5M €"` suffix-symbol (7), and `"2.6M"` with no currency
symbol at all (1). All euros in this sample, but the sample is two European
clubs. A parsed fee is **inferred, not measured**, and only ~18% of rows carry
one — so this cannot be modelled as Sportmonks' `amount INTEGER` column beside
a clean `type_id`.

### The `teams` slot sometimes contains a PLAYER, not a club

3,284 team sides in the sample: **17 have no id, 4 have no name.** Inspecting
the id-less names is where it gets bad — they include `Icardi Mauro`,
`Lemina Mario`, `Rony Lopes`, `Ouazane Abdellah`, `Karasu Eyup Can`,
`Kahraman Yusuf`, `Arac Ege`. **Those are people.** The vendor has put player
names in the club-name field.

Unguarded, that renders a club page for Mauro Icardi. It confirms the
Sportmonks precedent for real — `from_team_id` / `to_team_id` must not be
foreign keys, the name must be stored alongside the id, and **an id-less side
must render as plain text, never as a link** (same rule as unresolved entities
on the Sportmonks side).

### Dates are real but season-stamped, and one date is a batch sentinel

**Zero null dates** in 1,642 rows — and only 4 rows before 1990, so unknown
dates are *not* being mass-backfilled with a sentinel. But the distribution is
heavily clustered:

- **`2026-06-29` x50** — a bulk-stamped batch, almost certainly contract expiry
  written on one day rather than 50 real same-day moves.
- **`YYYY-07-01` dominates every year** (33 on 2025-07-01, 32 on 2022-07-01,
  29 on 2024-07-01, …) — the season-boundary convention, meaning "start of
  season", not the actual day of the move.

So date is trustworthy to the **season**, not the day. Any metric measuring an
interval in days from a transfer — "injured within N days of joining" — would
be corrupted by July-1 stamping and by the batch dates. Say season, not day.

### There is no transfer id, and the obvious composite key is not unique

The doc says to model a transfer as `(player, from, to, date)`. Measured
against the sample, that key **collides twice** — player 19034 has two byte-identical
rows for `2020-08-01 Ajax→Galatasaray` and two more for `2020-01-11 Galatasaray→Ajax`.
Identical, so collapsing loses nothing, but a `UNIQUE` constraint on that key
would either abort the ETL or silently drop rows depending on the insert mode.
Dedup has to be an explicit, counted step.

Duplication will also arrive *across* sources: a covered-club-to-covered-club
move appears in both clubs' team files and in the player's file.

### `page` is rejected, like `/injuries`

`/transfers?player=2741&page=2` → HTTP 200, `errors: {"page": "The Page field
do not exist."}`. Omit the field entirely. `paging.total` was 1 on every
response; the per-team calls returned 333 and 310 envelopes unpaginated, so
there is no evidence of a page ceiling to truncate against — but `truncated`
should still be recorded, because that assumption is exactly the kind that
went wrong on `/players`.

### Chain breaks make the doc's membership inference unsafe

The doc claims: *"Between two consecutive transfers the player can be assumed
to belong to the destination club."* Measured on the 6 probed players, that
fails often — 4 of 11 consecutive pairs for Piccoli, 3 of 15 for Rony Lopes,
3 of 10 for Bistrović, 2 of 10 for Lammers, 1 of 12 for Ryan.

The mechanism is visible in Piccoli's history: `2022-01-25 Atalanta→Genoa
(Loan)` is followed by `2022-07-01 Atalanta→Verona (Loan)`. There is no
`Genoa→Atalanta` return row — **loan returns are recorded inconsistently**,
sometimes explicitly, sometimes as `N/A`, sometimes not at all. Reconstructing
"which club did this player belong to on date X" from transfers alone is
therefore inference with a measurable error rate, not a lookup.

### Also present

`update` (an ISO timestamp) on every player envelope — the hook for incremental
refresh during transfer windows, without re-crawling everything.

### Built the same day: crawl, schema, ETL, queries, app

`ingest/apifootball/transfers.py` — two subjects, `team` before `player` in
`SUBJECT_ORDER` so an interrupted `--target all` always buys the cheap wide pass
first. Uses `client.get`, not `get_all`, because `page` is rejected; records
`paging_total` anyway, since a value other than 1 is the only warning we would
ever get that the endpoint started paginating. `report_paging_anomalies()` reads
it — deliberately, after `truncated` spent weeks being recorded faithfully and
never read.

**The cascade.** `--include-discovered` folds player ids named *only* by cached
team transfer files into the player work list. Those players are unreachable
through `/players`, `/injuries` or `/fixtures`, all of which are capped at
2020–2025. The player work list is also the union of `/players` **and**
`/injuries`, because a player injured for a whole season never appears in
`/players` — the 120 orphans. A crawl driven by `/players` alone would skip
exactly the players this project is about.

**Schema.** `af_transfer` + `af_transfer_type`, with the fee parse living in the
mapping table so all 112+ distinct strings are inspectable in one place rather
than buried in a regex. Fee is stored three ways — `fee_amount`,
`fee_currency`, `fee_eur` — so the bare `"2.6M"` case (amount known,
denomination unstated) cannot be silently counted as euros. `fee_format` records
which of `sym_num` / `num_sym` / `bare` matched, making a mis-parse visible by
format instead of requiring every string to be eyeballed.

`from_team_id` / `to_team_id` are **not** foreign keys and the names are stored
beside them, for two independently measured reasons: careers span clubs outside
these 47 competitions, and the vendor sometimes puts a person in the club field.

**Dedup is explicit and counted.** `collect_transfers()` keys on the fact
`(player, date, type, from, to)` — excluding `source`, since the same move seen
from a club and from the player is one transfer — and records `collapsed`,
`confirmed_by_both` and `duplicate_within_subject` separately in
`af_data_quality`. Cross-source agreement and true vendor duplication are
different things and collapsing them would have hidden both. No `UNIQUE`
constraint, because the documented natural key is not unique.

**Two new ETL guards**, both for failures that would produce plausible numbers:
an `unknown` category share above 35% (measured baseline ~21%, almost all of it
the vendor's own `N/A`) flags a probably-unparsed new type or fee format; any
non-euro `fee_currency` is reported explicitly, because those rows carry
`fee_amount` but not `fee_eur`, so every euro total silently excludes them.

**App.** `/af/transfers` overview, plus career tables on the player page and
in/out tables on the team page, all through new `af/_macros.html` macros —
`transfer_type` renders the *category*, never the raw mixed string, and
`transfer_fee` distinguishes a euro amount from an undenominated one from
"free" (where no fee is correct, not missing). Both club sides go through the
existing `af_entity_link`, which already renders an id-less entity as plain
text; the query layer also returns explicit `from_linkable` / `to_linkable`
flags so a template cannot get it wrong by forgetting to check.

`tests/test_af_transfers.py` covers every fee format and category value measured
above, both dedup paths, the id-less side, and the `af_unmapped_transfer_type`
invariant in both directions. Not yet run at the time of writing.
