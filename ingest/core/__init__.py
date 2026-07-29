"""Vendor-neutral ingestion primitives.

Everything here is true of *any* vendor we ingest from — the raw-JSON cache and
calendar-month arithmetic. Anything that encodes how a specific API meters,
paginates or authenticates belongs in that vendor's package instead.

Deliberately NOT here: the throttle model. Sportmonks meters per-entity
rolling-hour buckets; API-Football meters a global daily quota plus a
per-minute cap reported in response headers. A single abstraction over both
would model neither correctly, so each vendor client owns its own pacing.
"""
