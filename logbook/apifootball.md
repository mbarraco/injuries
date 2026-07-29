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
