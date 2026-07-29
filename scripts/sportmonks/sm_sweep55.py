#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Sportmonks 55-league sweep — for use ONLY once the Pro trial is active and
all 55 UEFA leagues have been selected in MySportmonks.

Replaces the marketing-page coverage proxy
(data/reference/sportmonks/coverage_uefa55.json)
with REAL measured injury data, mirroring exactly what probe.py --mode counts
did for API-Football: per league, per time period, how many `sidelined`
records actually exist.

Samples EVERY month of the last 3 years (36 consecutive calendar months) per
league, not a sparse spot-check — sparse sampling across an 11-year span can
miss or misjudge a league's real depth entirely (a league whose data only
exists in an unsampled year would wrongly read as dark). Calendar months are
used rather than per-country football-season boundaries (Aug-May for most of
Europe, but Mar-Nov for several Nordic/Baltic leagues) to avoid guessing each
country's calendar; results are bucketed into 3 rolling 12-month periods for
readability, which approximates but won't perfectly align with API-Football's
season-year definitions for calendar-year-season leagues.

Cost: 53 leagues x 36 months = ~1900 Fixture-entity calls, well under Pro's
3000/hr quota. Fetched with --concurrency (default 3) requests in flight at
once per league — Sportmonks' limit is a rolling hourly bucket, not a burst
cap, so concurrency here trades wall-clock time for the same total calls.
UNTESTED against Sportmonks though — watch the first run for 429s.

Tiers reuse the SAME thresholds already used for the API-Football report
(rich >=1000/yr, moderate 100-999, thin 10-99, token <10) so the two
providers are directly comparable for the first time.

Usage:
    python sm_sweep55.py
    python sm_sweep55.py --months 12   # just the most recent year, faster
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
COVERAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                             "reference", "sportmonks", "coverage_uefa55.json")
RESULTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                            "reference", "sportmonks", "measured_uefa55.json")
RAW_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "raw",
                             "sportmonks", "fixtures")
# Same coverage.db FILE probe.py writes to, but its own dedicated TABLE
# (see below) — one database, one table per provider for now. Still beats
# scattering results across separate JSON files with no shared query surface.
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "coverage.db")


# --------------------------------------------------------------------------- #
# SQLite storage — a dedicated table for Sportmonks rather than reusing
# probe.py's generic provider-column `coverage` table. The two providers'
# natural granularity differs (API-Football: per league per season-year;
# Sportmonks: per league per rolling year-bucket label) enough that forcing
# them into one generic shape was already an awkward fit. Separate, plainly-
# named tables per provider for now; probe.py's existing tables are untouched.
# `probe_run` is the one shared table — it's a generic, provider-tagged run
# log with no shape mismatch, so sharing it is harmless.
# --------------------------------------------------------------------------- #
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS probe_run (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            provider  TEXT NOT NULL,
            run_at    TEXT NOT NULL,
            notes     TEXT
        );
        CREATE TABLE IF NOT EXISTS sportmonks_coverage (
            run_id        INTEGER NOT NULL,
            country       TEXT NOT NULL,
            league        TEXT NOT NULL,
            sportmonks_id TEXT,
            year_bucket   TEXT NOT NULL,
            record_count  INTEGER NOT NULL,
            tier          TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def start_run(conn, provider, notes=""):
    cur = conn.execute(
        "INSERT INTO probe_run (provider, run_at, notes) VALUES (?, ?, ?)",
        (provider, datetime.now(timezone.utc).isoformat(timespec="seconds"), notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_sportmonks_coverage(conn, run_id, country, league, sportmonks_id, year_bucket,
                             count, tier):
    conn.execute(
        "INSERT INTO sportmonks_coverage VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, country, league, str(sportmonks_id) if sportmonks_id is not None else None,
         year_bucket, count, tier),
    )
    conn.commit()


def month_windows(n_months, end=None):
    """n_months consecutive (start, end-exclusive) monthly windows, oldest first."""
    end = end or date.today()
    months = []
    y, m = end.year, end.month
    for _ in range(n_months):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    windows = []
    for y, m in months:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        windows.append((f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"))
    return windows


# Tier thresholds — same language as the API-Football report, per rolling year.
RICH, MODERATE, THIN = 1000, 100, 10

# Concurrency is now the throttle, not a fixed per-call delay: Sportmonks'
# documented limit is a rolling HOURLY bucket per entity (3000/hr for
# Fixture), not a per-second burst cap — so N requests in flight is fine as
# long as total calls/hour stay under quota. This sweep needs ~1900 calls,
# well under 3000, so running concurrently doesn't risk the hourly ceiling.
# UNTESTED: we've never confirmed Sportmonks has no separate, undocumented
# concurrency limit — start with a modest default (3) and watch the first
# run for unexpected 429s before trusting higher concurrency.
DEFAULT_CONCURRENCY = 3
_state = {"log": None}
_log_lock = threading.Lock()


def log_response(url, params, resp, elapsed):
    if not _state.get("log"):
        return
    safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:2000]}
    record = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url, "params": safe, "status": resp.status_code,
        "elapsed_s": round(elapsed, 3), "body": body,
    }, ensure_ascii=False) + "\n"
    # Concurrent workers all write to the same log file — without a lock,
    # interleaved writes from different threads could corrupt a JSONL line.
    with _log_lock:
        with open(_state["log"], "a", encoding="utf-8") as f:
            f.write(record)


def get(session, token, url, params=None, max_retries=4):
    """No proactive pacing — concurrency is capped by the thread pool's
    worker count (see main loop), which is the actual rate limiter now."""
    p = {"api_token": token}
    p.update(params or {})
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        r = session.get(url, params=p, timeout=30)
        log_response(url, p, r, time.monotonic() - t0)
        if r.status_code != 429:
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        retry_after = r.headers.get("Retry-After")
        wait = int(retry_after) if (retry_after or "").isdigit() else min(60, 10 * (2 ** attempt))
        print(f"\n    429; waiting {wait}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)
    return 429, None


def get_all_fixtures(session, token, url, params, max_pages=5):
    """Follow pagination so a busy league/window can't silently truncate.

    Sportmonks' default page size is small (observed 50 elsewhere); a top
    league can have 30-50+ fixtures in a one-month window, so a single
    unpaginated call risks under-counting exactly the leagues that matter
    most. per_page=100 plus explicit has_more handling makes this exhaustive.
    """
    all_fixtures = []
    page = 1
    last_status = 200
    first_body = None
    while page <= max_pages:
        p = dict(params)
        p["per_page"] = 100
        p["page"] = page
        status, body = get(session, token, url, p)
        last_status = status
        if page == 1:
            first_body = body
        if status != 200:
            return last_status, all_fixtures, False, first_body
        batch = (body or {}).get("data", []) or []
        all_fixtures.extend(batch)
        pag = (body or {}).get("pagination") or {}
        if not batch or not pag.get("has_more"):
            return status, all_fixtures, False, first_body
        page += 1
    return last_status, all_fixtures, True, first_body  # hit max_pages — truncated


def cache_path(league_id, d1):
    return os.path.join(RAW_CACHE_DIR, f"{league_id}_{d1[:7]}.json")


def get_fixtures_cached(session, token, league_id, d1, d2, refresh=False):
    """Raw-response cache: one JSON file per (league, month), keyed by exactly
    what was queried. A hit skips the network call entirely, so a re-run
    only pays for months not yet fetched — and frees up a concurrency slot
    for a real fetch instead.

    Stores the FULL fixture list (not just a derived count) so future
    reprocessing — a different tier threshold, a field we didn't think to
    extract yet, rebuilding the DB from scratch — never needs to re-fetch.
    Written once here, this data outlives the 14-day Sportmonks trial.
    """
    path = cache_path(league_id, d1)
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        return 200, cached["fixtures"], cached.get("truncated", False), None, True

    url = f"{FOOTBALL}/fixtures/between/{d1}/{d2}"
    params = {"filters": f"fixtureLeagues:{league_id}", "include": "sidelined.sideline"}
    status, fixtures, truncated, first_body = get_all_fixtures(session, token, url, params)
    if status == 200:
        os.makedirs(RAW_CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "league_id": league_id, "window": [d1, d2],
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "truncated": truncated, "fixtures": fixtures,
            }, f, ensure_ascii=False)
    return status, fixtures, truncated, first_body, False


def report_quota(body):
    rl = (body or {}).get("rate_limit") or {}
    if rl:
        print(f"    quota: {rl.get('remaining')} left this hour "
              f"(entity={rl.get('requested_entity')}, resets in {rl.get('resets_in_seconds')}s)")


def section(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def format_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


# Timestamps of the most recent real fetches (cache hits excluded), used for
# a ROLLING-window ETA rather than a whole-run cumulative average. A
# cumulative average is slow to react to a recent speed-up or slow-down, and
# is noisy early in a run/resume when the total fetch count is still small.
_recent_fetch_times = deque(maxlen=30)


def render_progress(done, total, fetched, to_fetch, label, is_fetch):
    """Live in-place progress line. ETA reflects the last ~30 real fetches'
    throughput, not the whole run's average, so it tracks actual current
    speed (including mid-run changes from cache-hit bursts or concurrency
    effects) instead of a slow-moving historical blend.
    """
    if is_fetch:
        _recent_fetch_times.append(time.monotonic())
    width = 28
    frac = done / total if total else 1
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    remaining = to_fetch - fetched
    if len(_recent_fetch_times) >= 2 and remaining > 0:
        window_rate = ((_recent_fetch_times[-1] - _recent_fetch_times[0])
                       / (len(_recent_fetch_times) - 1))
        eta = format_duration(window_rate * remaining)
    elif remaining <= 0 and to_fetch > 0:
        eta = "done"
    else:
        eta = "…"
    line = (f"\r[{bar}] {done}/{total} ({100*frac:4.1f}%) · "
            f"fetched {fetched}/{to_fetch} · ETA {eta:>7} · {label}")
    print(line[:118].ljust(118), end="", flush=True)


def bucket_into_years(windows, values):
    """Chunk 36 (or N) monthly values into <=12-month buckets, most-recent-last.

    A trailing remainder (if N isn't a multiple of 12) becomes the OLDEST,
    smaller bucket — the recent buckets you actually care about stay full.
    """
    n = len(windows)
    full_buckets = n // 12
    remainder = n % 12
    sizes = ([remainder] if remainder else []) + [12] * full_buckets
    buckets, i = [], 0
    for size in sizes:
        label = f"{windows[i][0][:7]}..{windows[i + size - 1][0][:7]}"
        buckets.append((label, sum(values[i:i + size])))
        i += size
    return buckets  # oldest first


def tier_of(total):
    if total >= RICH:
        return "rich"
    if total >= MODERATE:
        return "moderate"
    if total >= THIN:
        return "thin"
    if total > 0:
        return "token"
    return "dark"


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Sportmonks 55-league sweep (Pro trial)")
    ap.add_argument("--months", type=int, default=36,
                    help="how many most-recent consecutive calendar months to "
                         "sample per league (default 36 = last 3 years, every "
                         "month — no sparse sampling)")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the raw-response cache and re-fetch everything "
                         "from the API (normally a re-run reuses cached months)")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help=f"concurrent in-flight requests per league (default "
                         f"{DEFAULT_CONCURRENCY}). Sportmonks' quota is an "
                         f"hourly bucket, not a burst limit, and this sweep "
                         f"uses well under the hourly cap either way — but "
                         f"concurrency here is UNTESTED against Sportmonks, "
                         f"so watch the first run for unexpected 429s before "
                         f"raising this. --concurrency 1 = old sequential "
                         f"behavior.")
    args = ap.parse_args()
    windows = month_windows(args.months)

    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1
    if not os.path.exists(COVERAGE_FILE):
        print(f"! {COVERAGE_FILE} missing")
        return 1

    with open(COVERAGE_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    leagues = doc.get("leagues", [])

    conn = init_db()
    run_id = start_run(conn, "sportmonks",
                       f"sm_sweep55 months={args.months} refresh={args.refresh}")
    print(f"writing to -> {DB_PATH} (run_id={run_id})")

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-sweep55.{ts}.log")
    print(f"logging responses -> {_state['log']}")
    already_cached = sum(
        1 for lg in leagues for d1, _ in windows
        if os.path.exists(cache_path(lg["id"], d1))
    ) if not args.refresh else 0
    to_fetch = len(leagues) * len(windows) - already_cached
    print(f"raw cache -> {RAW_CACHE_DIR}")
    print(f"concurrency={args.concurrency} (per league; ETA below is measured "
          f"from real throughput, not a fixed estimate)")
    print(f"probing {len(leagues)} leagues x {len(windows)} months "
          f"({windows[0][0]} .. {windows[-1][0]}) = "
          f"{len(leagues) * len(windows)} total · {already_cached} already cached · "
          f"{to_fetch} new calls")

    section("SWEEP — every month, all leagues, dense recent-history measurement")
    print("Counting ALL `sidelined` pivot entries per fixture (matches the")
    print("method validated in sm_deep.py, which pulled a real closed 2014")
    print("injury record). Every calendar month is queried — no sparse")
    print("sampling — so a league can't be misjudged from an unlucky gap.\n")
    session = requests.Session()
    results = []
    first_quota_shown = False
    db_rows_written = 0
    calls_done, fetched_done = 0, 0
    calls_total = len(leagues) * len(windows)
    for i, lg in enumerate(leagues, 1):
        lid, country, lname = lg["id"], lg["country"], lg["league"]
        row = {"country": country, "league": lname, "id": lid, "months": {}}
        monthly = []
        cache_hits = 0

        # NOTE: Sportmonks returns HTTP 200 + empty data for out-of-plan
        # leagues (proven in sm_deep.py section C), not 403 — so this cannot
        # actually distinguish "not in plan" from "genuinely zero". We rely
        # on sm_check_plan.py having verified plan access upfront.
        #
        # Only the network fetch runs on worker threads (get_fixtures_cached
        # -> get -> requests.Session.get). All bookkeeping below — progress
        # bar, counters, dict writes — happens on the main thread as each
        # future completes, so the only cross-thread shared state is the log
        # file write (locked in log_response) and the read-only session/token.
        month_results = {}
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(get_fixtures_cached, session, token, lid, d1, d2, args.refresh): d1
                for d1, d2 in windows
            }
            for fut in as_completed(futures):
                d1 = futures[fut]
                status, fixtures, truncated, first_body, from_cache = fut.result()
                month_results[d1] = (status, fixtures, truncated, first_body, from_cache)
                calls_done += 1
                if from_cache:
                    cache_hits += 1
                else:
                    fetched_done += 1
                render_progress(calls_done, calls_total, fetched_done, to_fetch,
                                f"{country[:20]} {d1[:7]}" + (" (cache)" if from_cache else ""),
                                is_fetch=not from_cache)
                if not first_quota_shown and status == 200 and not from_cache:
                    report_quota(first_body)
                    first_quota_shown = True
                if truncated:
                    print(f"\n    ! {country} {d1[:7]}: hit page cap, count may be truncated")

        # as_completed() yields out of order under concurrency — reassemble
        # in chronological window order so bucket_into_years aligns correctly.
        for d1, d2 in windows:
            status, fixtures, truncated, first_body, from_cache = month_results[d1]
            if status != 200:
                row["months"][d1[:7]] = f"http_{status}"
                monthly.append(0)
                continue
            entries = [s for f in fixtures for s in (f.get("sidelined") or [])]
            n = len(entries)
            row["months"][d1[:7]] = n
            monthly.append(n)

        years = bucket_into_years(windows, monthly)
        row["year_buckets"] = years
        row["total"] = sum(monthly)
        row["latest_year_total"] = years[-1][1] if years else 0
        row["tier"] = tier_of(row["latest_year_total"])
        results.append(row)
        for label, bucket_total in years:
            save_sportmonks_coverage(conn, run_id, country, lname, lid, label,
                                     bucket_total, tier_of(bucket_total))
            db_rows_written += 1
        bar = " ".join(f"{lbl.split('..')[1]}:{v}" for lbl, v in years)
        cache_note = f" [{cache_hits} cached]" if cache_hits else ""
        print()  # close out the in-place progress line before this summary
        print(f"  [{i:2}/{len(leagues)}] {country:24} {lname:22} {bar}   "
              f"total={row['total']} tier={row['tier']}{cache_note}")

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "windows": windows, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results (full monthly detail) saved to {RESULTS_FILE}")

    section("SUMMARY — tiered on the MOST RECENT rolling year, same thresholds "
             "as the API-Football report")
    ranked = sorted(results, key=lambda r: -r["latest_year_total"])
    by_tier = {t: [r for r in ranked if r["tier"] == t]
               for t in ("rich", "moderate", "thin", "token", "dark")}

    def line(rs):
        return ", ".join(f"{r['country']} {r['latest_year_total']}" for r in rs) or "none"

    print(f"  RICH     (>={RICH}/yr):            {len(by_tier['rich'])}")
    print(f"     {line(by_tier['rich'])}")
    print(f"  MODERATE ({MODERATE}-{RICH-1}/yr):        {len(by_tier['moderate'])}")
    print(f"     {line(by_tier['moderate'])}")
    print(f"  THIN     ({THIN}-{MODERATE-1}/yr):          {len(by_tier['thin'])}")
    print(f"     {line(by_tier['thin'])}")
    print(f"  TOKEN    (1-{THIN-1}/yr):           {len(by_tier['token'])}")
    print(f"     {line(by_tier['token'])}")
    print(f"  DARK     (0):                 {len(by_tier['dark'])}")
    print(f"     {line(by_tier['dark'])}")

    print("\nCompare directly against the API-Football verified result "
          "(same tier definitions, per season):")
    print("  API-Football 2025: 10 rich, 8 moderate, 22 thin, 3 token, 12 dark")
    print(f"  Sportmonks (latest ~12mo): {len(by_tier['rich'])} rich, "
          f"{len(by_tier['moderate'])} moderate, {len(by_tier['thin'])} thin, "
          f"{len(by_tier['token'])} token, {len(by_tier['dark'])} dark")
    print("\nCaveat: buckets are rolling CALENDAR months, not each country's own")
    print("football-season boundaries (most of Europe: Aug-May; several Nordic/")
    print("Baltic leagues: Mar-Nov calendar-year seasons) — close enough for a")
    print("coverage verdict, not an exact season-for-season match.")
    print(f"\n{db_rows_written} year-bucket rows written to sportmonks_coverage "
          f"in {DB_PATH} (run_id={run_id})")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
