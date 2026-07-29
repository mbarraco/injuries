"""API-Football ingestion.

Shaped differently from the Sportmonks package, because the API is:

- **Injuries are a first-class endpoint** (`/injuries?league&season`), not
  something reconstructed from fixtures. One call per league-season.
- **Fixtures are fetched per league-season**, not per league-month.
- **Rate limiting is global** — a daily quota plus a per-minute cap, reported
  in response *headers* — not per-entity rolling-hour buckets.
- **Coverage is discoverable**: `/leagues` carries a per-season
  `coverage.injuries` flag, so the work list comes from the API itself rather
  than a hand-maintained reference file.

See `logbook/apifootball.md` for measured behaviour and
`docs/superpowers/plans/2026-07-29-apifootball-ingestion.md` for the plan.
"""
