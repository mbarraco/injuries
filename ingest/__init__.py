"""Multi-vendor ingestion.

- core:        vendor-neutral primitives (raw-JSON cache, month arithmetic).
- sportmonks:  fixtures -> `sidelined` absences, per-entity hourly quotas.
- apifootball: first-class `/injuries` endpoint, global daily + per-minute quota.

Each vendor package owns its own client, paths and runners. They share the
cache discipline — fetch once, write raw to disk, never re-fetch — and nothing
else, because their rate-limit models have no honest common abstraction.
"""
