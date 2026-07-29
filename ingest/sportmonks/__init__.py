"""Repeatable, throttle-aware Sportmonks ingestion.

- client:   shared HTTP layer (per-entity quota, retries).
- paths:    filesystem layout for the raw cache and reference data.
- resolve:  entity id -> name resolution into coverage.db.
- backfill: wide date-range fixture fetch + per-league watermark.
- enrich:   re-fetch cached entities with richer includes.
- squads:   team rosters, one bulk call per team.
- sync:     incremental fetch from the watermark onward.

Absences here are reconstructed from `sidelined` records riding on fixtures —
this API has no bulk injuries endpoint. See `logbook/sportmonks.md`.
"""
