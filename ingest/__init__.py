"""Repeatable, throttle-aware Sportmonks ingestion.

- sportmonks_client: shared HTTP layer (per-entity quota, retries, cache).
- resolve:            entity id -> name resolution into coverage.db.
- backfill:           wide date-range fixture fetch + per-league watermark.
- sync:               incremental fetch from the watermark onward.
"""
