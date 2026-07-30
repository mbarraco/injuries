"""Shared, throttle-aware HTTP layer for API-Football.

Deliberately NOT a subclass or sibling of `SportmonksClient` — the two APIs
meter requests in fundamentally different ways, and forcing one abstraction
over both would model neither correctly:

| | Sportmonks | API-Football |
|---|---|---|
| buckets | per entity (Fixture, Player, …) | one global bucket |
| windows | rolling hour from first call | rolling day **and** rolling minute |
| reported in | response body `rate_limit` | response **headers** |
| out-of-plan | HTTP 200, `data: []` — indistinguishable | HTTP 200, non-empty `errors` |

What they *do* share — cache-first fetching, credential-redacted logging,
bounded retry — lives in `ingest.core`.

Three behaviours worth knowing about:

- **Two windows, paced proactively.** 7,500/day is the budget; 300/min is the
  throttle. The minute window is enforced by spacing requests (thread-safe, so
  a worker pool can't burst past it); the daily window is a budget the caller
  checks *before* starting a long run, via `can_afford()`.
- **A 200 is not a success.** API-Football reports plan gating, auth failure
  and quota exhaustion in a non-empty `errors` field on an HTTP 200. Code that
  only checks `status == 200` will read a plan wall as real data absence. Use
  `classify()` — this is the one real advantage over Sportmonks, where the two
  cases genuinely cannot be told apart, and it's wasted if we don't check it.
- **`results: 0` with empty `errors` is a real, cacheable answer.** It means
  the vendor has no data, not that we failed. Verified 2026-07-23 against
  Belgium 2024 (see `logbook/apifootball.md`).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone

import requests

API = "https://v3.football.api-sports.io"

# Plan ceilings. Read from response headers on the first call and corrected in
# place, so these only ever seed the pacer/dry-run estimates before anything is
# observed — a wrong seed here does not throttle a live run, it only makes a
# --dry-run cost estimate wrong until the first real request lands.
# Pro measured 2026-07-29: 7,500/day, 300/min. Upgraded to Ultra same day,
# confirmed via /status: 75,000/day AND 450/min — both scaled, not just the
# daily figure.
DEFAULT_DAY_LIMIT = 75_000
DEFAULT_MINUTE_LIMIT = 450

# Fraction of the per-minute ceiling we actually aim for. Headroom matters
# because the vendor's window boundary and ours are not synchronised — pacing
# at exactly the limit puts every request near the edge of a 429.
MINUTE_SAFETY = 0.8

# Outcome classes for a response body. `OK` and `EMPTY` are both successes and
# both cacheable; the rest are failures with different remedies.
OK, EMPTY, PLAN_BLOCKED, AUTH_FAILED, QUOTA_EXHAUSTED, DAILY_EXHAUSTED, ERROR = (
    "ok", "empty", "plan_blocked", "auth_failed", "quota_exhausted",
    "daily_exhausted", "error")

# Outcomes that describe the DATA, and so are safe to persist. The others
# describe our ACCESS at a moment in time; caching one would freeze a temporary
# condition into the permanent record and hide the gap from every later run.
CACHEABLE_OUTCOMES = (OK, EMPTY)

# Outcomes that mean "stop the whole run now", as opposed to "this one item
# failed, move on". QUOTA_EXHAUSTED (a transient per-minute 429) is NOT here:
# get() already retries it internally, so if it still escapes as an outcome,
# retries were exhausted too and continuing is equally pointless.
STOP_OUTCOMES = (DAILY_EXHAUSTED, QUOTA_EXHAUSTED)

# Matches "daily" and standalone "day" but not e.g. "Sunday" or "matchday" —
# both observed vendor wordings ("your daily request limit", "limit for the
# day") satisfy this without over-matching unrelated text.
_DAILY_WORDING = re.compile(r"\bdaily\b|\bday\b")

# Distinctive rate-limit phrasing, checked before the plan/quota keywords since
# those appear in BOTH rate-limit and plan-gating messages. Kept narrow on
# purpose: "too many requests", an explicit per-minute window, or the literal
# words "rate limit" — all three observed 2026-07-29.
_RATE_LIMIT_WORDING = re.compile(
    r"too many requests|per[- ]minute|requests per minute|rate limit")


def classify(status, body):
    """Map an HTTP status + body to an outcome class. Returns (outcome, detail).

    API-Football signals problems inside a 200 response, so status alone is not
    enough. `errors` is `[]` when healthy and a dict of messages when not; the
    key names which subsystem complained (`plan`, `token`, `requests`, …).

    **The vendor is inconsistent about which status code carries daily
    exhaustion.** Measured 2026-07-29, same wall, same day: one run got it as
    HTTP 429 ("You have reached your daily request limit..."), a later run got
    the identical condition as HTTP **200** ("You have reached the request
    limit for the day..."). An earlier version of this function only checked
    for "daily" inside the `status == 429` branch, so the 200 case fell through
    to the generic quota-ish substring match below and was retried 5 times per
    call — the opposite of what daily exhaustion needs. The daily check must
    therefore run first, against the body, before any branch on status code.
    """
    if body is not None and isinstance(body, dict):
        errors = body.get("errors")
        if errors:
            text = json.dumps(errors) if isinstance(errors, dict) else str(errors)
            # Word-boundary match on both "daily" and "day" — a plain
            # substring check for "day" does NOT match "daily" (d-a-i-l-y has
            # no "d-a-y" run), which is exactly the wording the vendor used on
            # a genuine daily-limit 429 (measured 2026-07-29). Missing that
            # let the condition fall through to the generic quota match below
            # and be retried 5x per call before this was caught.
            if _DAILY_WORDING.search(text.lower()):
                return DAILY_EXHAUSTED, text

    if status is None:
        return ERROR, "no response"
    if status == 429:
        # Guard on the key's presence, not just body being a dict: a dict with
        # no "errors" key yields json.dumps(None) == "null", which is truthy
        # and would surface as the literal detail string "null".
        errors = body.get("errors") if isinstance(body, dict) else None
        return QUOTA_EXHAUSTED, (json.dumps(errors) if errors else "HTTP 429")
    if status in (401, 403):
        return AUTH_FAILED, f"HTTP {status}"
    if status != 200:
        return ERROR, f"HTTP {status}"
    if body is None:
        return ERROR, "empty body"

    errors = body.get("errors")
    # Healthy responses use [] — a dict here is always a complaint. Some
    # deployments return {} for healthy, so test emptiness, not type.
    if errors:
        text = json.dumps(errors) if isinstance(errors, dict) else str(errors)
        lowered = text.lower()
        if "token" in lowered or "api key" in lowered:
            return AUTH_FAILED, text
        # Rate limiting is matched FIRST, on its own distinctive wording,
        # because neither "plan" nor "limit" discriminates. All three observed
        # rate-limit messages (2026-07-29) name the window explicitly, and two
        # of them ALSO mention plan/subscription as an upsell:
        #   "...reached your per-minute request limit ... or upgrade your plan"
        #   "...exceeded the limit of requests per minute of your subscription"
        #   "Your rate limit is 450 requests per minute."
        # Ordering plan-before-quota misread the middle one as PLAN_BLOCKED;
        # ordering quota-before-plan would misread genuine plan gating that
        # mentions a limit. Matching the specific phrase avoids both.
        if _RATE_LIMIT_WORDING.search(lowered):
            return QUOTA_EXHAUSTED, text
        if "plan" in lowered or "subscription" in lowered:
            return PLAN_BLOCKED, text
        if "limit" in lowered or "reached" in lowered or "requests" in lowered:
            return QUOTA_EXHAUSTED, text
        return ERROR, text

    # No errors: a zero-result answer is genuine absence of data, not failure.
    return (OK, "") if body.get("results") else (EMPTY, "results=0")


class ApiFootballClient:
    """Thread-safe wrapper over a requests.Session.

    One instance is shared across worker threads. `requests.Session` is safe
    for concurrent GETs; the mutable shared state here (the pacer clock, the
    quota view, the log file) is each guarded by its own lock.
    """

    def __init__(self, key, log_path=None, max_retries=4,
                 minute_limit=DEFAULT_MINUTE_LIMIT, day_limit=DEFAULT_DAY_LIMIT):
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": key})
        self.log_path = log_path
        self.max_retries = max_retries

        self._log_lock = threading.Lock()
        self._quota_lock = threading.Lock()
        self._pace_lock = threading.Lock()

        self.minute_limit = minute_limit
        self.day_limit = day_limit
        self._day_remaining = None
        self._minute_remaining = None
        self._next_slot = 0.0  # monotonic time the next request may start
        self.calls_made = 0

    # ------------------------------------------------------------------ #
    # Pacing — spread requests across the minute window.
    # ------------------------------------------------------------------ #
    @property
    def min_interval(self):
        """Seconds between request starts to stay under the minute ceiling."""
        target = max(1.0, self.minute_limit * MINUTE_SAFETY)
        return 60.0 / target

    def _reserve_slot(self):
        """Claim the next send slot, then sleep until it arrives.

        The reservation happens under a lock but the sleep does not, so N
        threads take N distinct slots and wait concurrently rather than
        serialising. Without this, a pool of workers would fire simultaneously
        and blow through the per-minute ceiling regardless of the interval.
        """
        with self._pace_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.min_interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    # ------------------------------------------------------------------ #
    # Quota — read from response headers, corrected on every call.
    # ------------------------------------------------------------------ #
    def _record_quota(self, headers):
        if not headers:
            return

        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        # Header names differ in case between the two windows; requests'
        # header mapping is case-insensitive, so look them up plainly.
        day_remaining = as_int(headers.get("x-ratelimit-requests-remaining"))
        day_limit = as_int(headers.get("x-ratelimit-requests-limit"))
        minute_remaining = as_int(headers.get("X-RateLimit-Remaining"))
        minute_limit = as_int(headers.get("X-RateLimit-Limit"))
        with self._quota_lock:
            if day_remaining is not None:
                self._day_remaining = day_remaining
            if day_limit:
                self.day_limit = day_limit
            if minute_remaining is not None:
                self._minute_remaining = minute_remaining
            if minute_limit:
                # Correcting this also widens/narrows min_interval for every
                # subsequent request, so a wrong seed self-heals after one call.
                self.minute_limit = minute_limit

    def quota(self):
        with self._quota_lock:
            return {
                "day_remaining": self._day_remaining,
                "day_limit": self.day_limit,
                "minute_remaining": self._minute_remaining,
                "minute_limit": self.minute_limit,
                "calls_made": self.calls_made,
            }

    def can_afford(self, calls):
        """Whether `calls` more requests fit in today's remaining budget.

        Returns (affordable, remaining). Unknown remaining (nothing observed
        yet) counts as affordable — this is a pre-flight courtesy, not a
        guarantee, and it must never block a run on missing information.
        """
        with self._quota_lock:
            remaining = self._day_remaining
        if remaining is None:
            return True, None
        return calls <= remaining, remaining

    # ------------------------------------------------------------------ #
    # Logging — one JSON object per line. The key lives in a header and is
    # never written; params are logged in full.
    # ------------------------------------------------------------------ #
    def _log(self, url, params, status, elapsed, body, headers=None):
        if not self.log_path:
            return
        record = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "url": url,
            "params": params or {},
            "status": status,
            "elapsed_s": round(elapsed, 3),
            "quota": {k: v for k, v in (headers or {}).items()
                      if k.lower().startswith("x-ratelimit")},
            "body": body,
        }, ensure_ascii=False) + "\n"
        with self._log_lock:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(record)

    # ------------------------------------------------------------------ #
    # Core GET.
    # ------------------------------------------------------------------ #
    def get(self, path, params=None):
        """GET one endpoint. Returns (status, body, outcome, detail).

        Handles 429 with an authoritative `Retry-After` where offered, and
        transient 5xx/network errors with bounded backoff. A quota-exhaustion
        message delivered as a 200 body is retried the same way as a 429 —
        the vendor uses both for the same condition.
        """
        url = f"{API}{path}"
        for attempt in range(self.max_retries + 1):
            self._reserve_slot()
            start = time.monotonic()
            try:
                response = self.session.get(url, params=params or {}, timeout=30)
            except requests.RequestException as error:
                self._log(url, params, None, time.monotonic() - start,
                          {"_error": str(error)})
                if attempt == self.max_retries:
                    return None, None, ERROR, str(error)
                time.sleep(min(30, 2 ** attempt))
                continue

            elapsed = time.monotonic() - start
            try:
                body = response.json()
            except ValueError:
                body = None
            self._log(url, params, response.status_code, elapsed, body,
                      response.headers)
            self._record_quota(response.headers)
            with self._quota_lock:
                self.calls_made += 1

            outcome, detail = classify(response.status_code, body)

            if outcome == DAILY_EXHAUSTED:
                # Never retry: the window resets in hours, not seconds. Force
                # day_remaining to 0 directly rather than trust the headers —
                # they are either absent (measured on a 429 delivery) or
                # present but STALE, still showing the pre-exhaustion count
                # (measured on a 200 delivery, same day: headers read 7499
                # while the body said the day's limit was reached). Either
                # way the header cannot be relied on to reflect exhaustion.
                with self._quota_lock:
                    self._day_remaining = 0
                return response.status_code, body, outcome, detail

            if outcome == QUOTA_EXHAUSTED:
                if attempt == self.max_retries:
                    return response.status_code, body, outcome, detail
                retry_after = response.headers.get("Retry-After")
                wait = (int(retry_after) if (retry_after or "").isdigit()
                        else min(60, 10 * 2 ** attempt))
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                if attempt == self.max_retries:
                    return response.status_code, body, outcome, detail
                time.sleep(min(30, 2 ** attempt))
                continue

            return response.status_code, body, outcome, detail
        return None, None, ERROR, "retries exhausted"

    # ------------------------------------------------------------------ #
    # Pagination — API-Football reports paging.current / paging.total.
    # ------------------------------------------------------------------ #
    def get_all(self, path, params=None, max_pages=500):
        """Fetch every page. Returns (items, outcome, detail, truncated).

        `truncated` is True only when max_pages was reached with pages still
        outstanding — the caller's signal that the result is incomplete rather
        than merely small. A partial failure mid-pagination returns the pages
        gathered so far alongside the failing outcome, so nothing already paid
        for is discarded.

        **max_pages is a safety valve, not a budget.** Pagination stops
        naturally at `paging.total`, so a high ceiling costs nothing on small
        responses. It was 50, which capped /players at 1,000 records and
        silently truncated 20 league-seasons — La Liga, the Premier League,
        both big UEFA cups — i.e. exactly the competitions with the most
        players. Set high enough that hitting it means something is genuinely
        wrong rather than merely large.

        **`page` is omitted from the first request.** API-Football's endpoints
        are not uniform: `/injuries` rejects the field outright with
        `errors: {"page": "The Page field do not exist."}` on an HTTP 200,
        which classifies as a hard error and returns zero records. Sending it
        only from page 2 onward keeps non-paginating endpoints working while
        leaving paginating ones unaffected (page 1 is their default anyway).
        Measured 2026-07-29 — see `logbook/apifootball.md`.
        """
        items, page, truncated = [], 1, False
        while page <= max_pages:
            merged = dict(params or {})
            if page > 1:
                merged["page"] = page
            status, body, outcome, detail = self.get(path, merged)
            if outcome not in (OK, EMPTY):
                return items, outcome, detail, truncated
            items.extend((body or {}).get("response") or [])
            paging = (body or {}).get("paging") or {}
            total = paging.get("total") or 1
            if page >= total:
                return items, (OK if items else EMPTY), "", truncated
            page += 1
        return items, OK, "", True
