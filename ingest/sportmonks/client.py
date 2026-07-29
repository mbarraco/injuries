"""Shared, throttle-aware HTTP layer for Sportmonks.

Everything the ingestion runners share lives here so the throttling and
caching behaviour is defined once and identically:

- **Per-entity quota tracking.** Sportmonks rate-limits per entity (Fixture,
  Player, Team, League, Season, Type each get their own rolling-hour bucket);
  exhausting one does not touch the others. Every response carries a
  `rate_limit` block naming the `requested_entity` it was billed to, so we
  record remaining quota keyed by that entity and let callers pace a large
  batch against the right bucket instead of guessing.
- **Reactive 429 handling.** A real 429 returns an authoritative
  `Retry-After`; we sleep exactly that long and retry. Proven against a live
  rate-limit hit during earlier work.
- **Bounded retry for 5xx/network blips**, then give up cleanly so one bad
  request never aborts a long run.
- **Cache-first fetching.** Every raw response is written to disk keyed by
  exactly what was queried, and a cache hit skips the network entirely. This
  is what lets the data outlive the 14-day trial: once fetched, a record is
  never re-fetched and never lost.

Deliberately domain-agnostic: no knowledge of leagues, fixtures, or data
paths. The runners layer that on top.

The raw-JSON cache helpers this module used to carry now live in
`ingest.core.cache` — they were never Sportmonks-specific.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

import requests

# The entity names Sportmonks reports in rate_limit.requested_entity — each is
# an independent rolling-hour quota bucket. Verified from captured responses
# (capitalised singular, e.g. "Fixture"), so runners can reference a bucket
# symbolically. Quota lookups are case-insensitive, so these double as the
# canonical spelling without being fragile about it.
FIXTURE, PLAYER, TEAM, LEAGUE, TYPE, COUNTRY = (
    "Fixture", "Player", "Team", "League", "Type", "Country")
ENTITIES = (FIXTURE, PLAYER, TEAM, LEAGUE, TYPE, COUNTRY)


class SportmonksClient:
    """Thread-safe wrapper over a requests.Session with quota + retry logic.

    A single instance is shared across worker threads. requests.Session is
    safe for concurrent GETs; the only mutable shared state (the log file and
    the quota view) is guarded by locks.
    """

    def __init__(self, token, log_path=None, max_retries=4):
        self.token = token
        self.session = requests.Session()
        self.log_path = log_path
        self.max_retries = max_retries
        self._log_lock = threading.Lock()
        self._quota_lock = threading.Lock()
        self._quota = {}

    # ------------------------------------------------------------------ #
    # Logging — one JSON object per line, api_token always redacted.
    # ------------------------------------------------------------------ #
    def _log(self, url, params, status, elapsed, body):
        if not self.log_path:
            return
        safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
        record = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "url": url, "params": safe, "status": status,
            "elapsed_s": round(elapsed, 3), "body": body,
        }, ensure_ascii=False) + "\n"
        with self._log_lock:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(record)

    # ------------------------------------------------------------------ #
    # Quota — recorded per entity from every response's rate_limit block.
    # ------------------------------------------------------------------ #
    def _record_quota(self, body):
        rate = (body or {}).get("rate_limit") or {}
        entity = rate.get("requested_entity")
        if not entity:
            return
        with self._quota_lock:
            self._quota[str(entity).lower()] = {
                "remaining": rate.get("remaining"),
                "resets_in_seconds": rate.get("resets_in_seconds"),
                "observed_at": time.monotonic(),
            }

    def quota(self, entity):
        """Last-seen quota for an entity, or None if we've never billed it."""
        with self._quota_lock:
            snapshot = self._quota.get(str(entity).lower())
            return dict(snapshot) if snapshot else None

    def quota_snapshot(self):
        with self._quota_lock:
            return {entity: dict(value) for entity, value in self._quota.items()}

    def await_quota(self, entity, safety_margin=1):
        """Proactively pause if the given entity's bucket is (near) exhausted.

        Complements the reactive 429 handler: rather than firing a burst of
        requests that all come back 429, a runner calls this between batches so
        it waits out the rolling-hour window *before* hammering an entity that
        has nothing left. Because buckets are per-entity, pausing on Fixture
        never blocks Player/Team work.

        Best-effort and self-correcting: if we've never billed this entity yet
        (nothing observed) or its window has already reset, it returns
        immediately — it can only ever add safety, never make things worse.
        Returns the seconds actually waited.
        """
        snapshot = self.quota(entity)
        if not snapshot or snapshot.get("remaining") is None:
            return 0.0
        if snapshot["remaining"] >= safety_margin:
            return 0.0
        resets_in = snapshot.get("resets_in_seconds") or 0
        elapsed = time.monotonic() - snapshot["observed_at"]
        wait = resets_in - elapsed
        if wait <= 0:
            return 0.0
        wait += 1  # small buffer so we resume just past the reset boundary
        print(f"    {entity} quota exhausted; waiting {int(wait)}s for reset")
        time.sleep(wait)
        return wait

    # ------------------------------------------------------------------ #
    # Core GET — handles 429 (authoritative Retry-After) and transient
    # 5xx / network errors with bounded backoff. Returns (status, body);
    # status is None only when every network attempt raised.
    # ------------------------------------------------------------------ #
    def get(self, url, params=None):
        merged = {"api_token": self.token}
        merged.update(params or {})
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                response = self.session.get(url, params=merged, timeout=30)
            except requests.RequestException as error:
                # Network blip: back off and retry, but never busy-loop.
                self._log(url, merged, None, time.monotonic() - start, {"_error": str(error)})
                if attempt == self.max_retries:
                    return None, None
                time.sleep(min(30, 2 ** attempt))
                continue

            elapsed = time.monotonic() - start
            try:
                body = response.json()
            except ValueError:
                body = None
            self._log(url, merged, response.status_code, elapsed, body)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after or "").isdigit() else min(60, 10 * 2 ** attempt)
                if attempt == self.max_retries:
                    return 429, None
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                if attempt == self.max_retries:
                    return response.status_code, body
                time.sleep(min(30, 2 ** attempt))
                continue

            self._record_quota(body)
            return response.status_code, body
        return None, None


    # ------------------------------------------------------------------ #
    # Pagination — follow has_more so a busy window can't silently truncate.
    # ------------------------------------------------------------------ #
    def get_all(self, url, params=None, per_page=100, max_pages=50):
        """Return (status, items, truncated, first_body).

        `truncated` is True only if we hit max_pages with more data still
        available — the caller's signal that the count may be incomplete.
        `first_body` is page 1's raw body (for quota/error inspection).
        """
        items, page, first_body, last_status = [], 1, None, 200
        while page <= max_pages:
            merged = dict(params or {})
            merged["per_page"] = per_page
            merged["page"] = page
            status, body = self.get(url, merged)
            last_status = status
            if page == 1:
                first_body = body
            if status != 200:
                return status, items, False, first_body
            batch = (body or {}).get("data") or []
            items.extend(batch)
            pagination = (body or {}).get("pagination") or {}
            if not batch or not pagination.get("has_more"):
                return status, items, False, first_body
            page += 1
        return last_status, items, True, first_body
