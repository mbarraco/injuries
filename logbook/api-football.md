# API-Football — knowledge log

Append-only, one dated section per day of work. Never edit a previous day's
entry — add a new dated section at the bottom instead, even to correct
something (note the correction and link back).

---

## 2026-07-23

### Auth & access
- Header auth: `x-apisports-key: <key>`.
- Direct signup (dashboard.api-football.com), not RapidAPI — simpler for scripting.
- Free tier: ~100 requests/day, ~10/min. Paid plan used here: 7500/day, 300/min.
- Free tier blocks querying the **current** season's data (returns an
  `errors` object / `plan✗`); only older seasons are queryable for free.

### Endpoints & response shape
- `GET /leagues` returns the **entire** league list (1235 leagues) in a
  single unpaginated call — confirmed consistent across 4 independent runs,
  no pagination handling needed here.
- `GET /injuries?league={id}&season={year}` — `season` is the season's
  **start year** (e.g. `season=2023` means the 2023/24 season).
- The `results` field in the injuries response is the **true total count**
  of matching records, not a page size — safe to read directly for counting
  without iterating or paginating the `response` array.

### The coverage.injuries flag — authoritative, verified
- Each league object in `/leagues` has a `seasons[]` array; each season has
  `coverage.injuries` (bool). This flag is **directly readable for free**
  from the one `/leagues` call — no per-league injury query needed to know
  whether a league is covered.
- **Verified accurate**: cross-checked the flag against real per-league
  injury counts for all 55 UEFA top-flight leagues across 3 seasons. Every
  flagged-YES league returned >0 real records; every flagged-NO league
  returned exactly 0. Trust this flag.
- Flag=YES does **not** mean richly covered — record volume varies from 1
  to 3800+ per league/season even among flagged leagues. Don't stop at the
  boolean; count records too if volume matters.

### Data findings (2026-07-23 snapshot)
- 43/55 UEFA leagues flagged covered for the 2025/26 season; 12 dark
  (data doesn't exist for these leagues at all: Albania, Andorra, Belarus,
  Faroe Islands, Gibraltar, Hungary, Iceland, Kosovo, Malta, Montenegro,
  San Marino, Serbia) + Liechtenstein (no domestic league at all).
- Tiering the 43 by real 2025 volume (rich ≥1000, moderate 100-999,
  thin 10-99, token 1-9): 10 rich, 8 moderate, 22 thin, 3 token.
- **History is much narrower than breadth**: only 11 leagues have ANY
  injury data for 2023 or 2024 (England, Spain, Germany, Italy, France,
  Netherlands, Denmark, Norway, Sweden, Russia, Turkey) — all with rich
  volume (776-3853 records/season). Every other league returns a hard 0
  for 2023/2024 even if well-populated for 2025 — their injury tracking
  appears to have started around 2025, not backfilled.

### Rate limiting
- Standard daily + per-minute quota, `x-ratelimit-*` response headers
  report remaining quota. Simple 429 + Retry-After handling worked without
  surprises — nothing unusual here compared to Sportmonks (see that log).
