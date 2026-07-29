"""Wide date-range fixture fetch — the historical backfill.

Fetches `sidelined.sideline` data per (league, calendar month) across an
arbitrary date range and caches each month to disk. Resumable: a month
already cached is skipped, so re-running only pays for what's missing — the
whole point, given quota resets hourly and the trial is time-boxed.

Also maintains a per-league **watermark** (the latest month fetched) so the
incremental `sync` runner knows where to resume. After fetching, it resolves
every newly-referenced player/team/type into `coverage.db` so the raw cache
and the reference tables stay in step.

Replaces the original `sm_sweep55.py` and the fixture-scanning half of
`sm_resolve_entities.py`. Exposes its fetch/watermark helpers for `sync.py`
to reuse.

Usage:
    python -m ingest.backfill                      # 2014-01 .. now, all leagues
    python -m ingest.backfill --since 2022-01      # narrower range
    python -m ingest.backfill --months 36          # most recent N months
    python -m ingest.backfill --no-resolve         # fetch only, skip resolve
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dotenv import load_dotenv

from ingest.core import months
from ingest.core.cache import read_cache, write_cache
from ingest.sportmonks import paths, resolve
from ingest.sportmonks.client import FIXTURE, SportmonksClient

DEFAULT_SINCE = "2014-01"  # logbook-verified: real archive reaches at least here
DEFAULT_CONCURRENCY = 3

# Include sets for the fixtures/between call. The history backfill uses the thin
# BASE set (just injuries — fast, small responses). The enrichment pass
# (ingest/enrich.py) re-fetches with the RICH set to capture the full match
# record; since one request bills the same regardless of how many includes ride
# on it (rate-limits doc), the extra data is free per call. `weather` (404 for
# many fixtures) and `odds` (403 — separate product) are deliberately excluded.
BASE_FIXTURE_INCLUDE = "sidelined.sideline"
RICH_FIXTURE_INCLUDE = (
    "sidelined.sideline;participants;lineups.details;events;statistics;"
    "formations;referees;venue;coaches;periods;state;scores"
)


# --------------------------------------------------------------------------- #
# Fixture fetch — cache-first. The cached file keeps the SAME shape the
# original sweep wrote, so app/etl.py reads new and old cache files alike.
# --------------------------------------------------------------------------- #
def fetch_fixture_window(client, league_id, d1, d2, refresh=False,
                         include=BASE_FIXTURE_INCLUDE):
    """Return (fixtures, truncated, from_cache) for one league-month window.

    On a cache miss the raw fixtures are written to disk before returning, so
    a downloaded month is never lost even if a later step in the run fails. The
    `include` used is recorded in the cache file so the enrichment pass can tell
    a thin (base) month from an already-enriched one.
    """
    path = paths.fixture_cache_path(league_id, d1[:7])
    if not refresh:
        cached = read_cache(path)
        if cached is not None:
            return cached.get("fixtures", []), cached.get("truncated", False), True

    url = f"{paths.FOOTBALL}/fixtures/between/{d1}/{d2}"
    params = {"filters": f"fixtureLeagues:{league_id}", "include": include}
    status, fixtures, truncated, _first = client.get_all(url, params)
    if status != 200:
        return None, truncated, False
    write_cache(path, {
        "league_id": league_id, "window": [d1, d2], "include": include,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "truncated": truncated, "fixtures": fixtures,
    })
    return fixtures, truncated, False


def fetch_league(client, league_id, windows, concurrency, refresh=False):
    """Fetch every window for one league; windows fetched concurrently.

    All fixture calls share the single Fixture quota bucket, whose limit is a
    rolling-hour total (not a burst cap), so concurrent in-flight requests are
    safe as long as hourly volume stays under quota.

    Returns {"fetched", "cached", "failed", "latest_ok"} where latest_ok is
    the newest month (YYYY-MM) that returned data, for the watermark.
    """
    stats = {"fetched": 0, "cached": 0, "failed": 0, "latest_ok": None}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(fetch_fixture_window, client, league_id, d1, d2, refresh): d1
                   for d1, d2 in windows}
        for future in as_completed(futures):
            d1 = futures[future]
            fixtures, _truncated, from_cache = future.result()
            if fixtures is None:
                stats["failed"] += 1
                continue
            stats["cached" if from_cache else "fetched"] += 1
            month = d1[:7]
            if stats["latest_ok"] is None or month > stats["latest_ok"]:
                stats["latest_ok"] = month
    return stats


# --------------------------------------------------------------------------- #
# Watermark — per-league latest month fetched, so sync knows where to resume.
# --------------------------------------------------------------------------- #
def read_watermark():
    return read_cache(paths.WATERMARK_FILE) or {}


def write_watermark(watermark):
    write_cache(paths.WATERMARK_FILE, watermark)


def advance_watermark(watermark, league_id, latest_month):
    """Move a league's watermark forward only — never backwards."""
    if not latest_month:
        return
    key = str(league_id)
    if key not in watermark or latest_month > watermark[key]:
        watermark[key] = latest_month


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #
def run_fetch(client, leagues, windows, concurrency, refresh=False):
    """Fetch `windows` for every league, updating the watermark as we go.

    The watermark is persisted after each league so an interrupted run keeps
    all progress up to the last completed league.
    """
    watermark = read_watermark()
    totals = {"fetched": 0, "cached": 0, "failed": 0}
    for index, league in enumerate(leagues, 1):
        league_id = league["id"]
        # Per-endpoint throttle: pause here if the shared Fixture bucket ran
        # dry on a previous league, instead of opening the next league only to
        # 429 every request. Doesn't touch the Player/Team buckets resolve uses.
        client.await_quota(FIXTURE)
        stats = fetch_league(client, league_id, windows, concurrency, refresh)
        for key in totals:
            totals[key] += stats[key]
        advance_watermark(watermark, league_id, stats["latest_ok"])
        write_watermark(watermark)
        # country alone stopped identifying a row once play-offs and the UEFA
        # club competitions joined the list (Russia now has two entries, and
        # four competitions share country=EUROPE), so name the league too.
        label = f"{league.get('country', '?')} · {league.get('league', '?')}"
        print(f"  [{index:2}/{len(leagues)}] {label:46.46} "
              f"fetched={stats['fetched']} cached={stats['cached']} "
              f"failed={stats['failed']} watermark={watermark.get(str(league_id))}")
    print(f"\nfetch totals: fetched={totals['fetched']} cached={totals['cached']} "
          f"failed={totals['failed']}")
    return totals


def make_client(name):
    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return None
    os.makedirs(paths.LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(paths.LOG_DIR, f"sportmonks-{name}.{stamp}.log")
    print(f"logging responses -> {log_path}")
    return SportmonksClient(token, log_path=log_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sportmonks historical backfill")
    parser.add_argument("--since", default=DEFAULT_SINCE,
                        help=f"earliest month to fetch, YYYY-MM (default {DEFAULT_SINCE})")
    parser.add_argument("--until", default=months.current_ym(),
                        help="latest month to fetch, YYYY-MM (default: current month)")
    parser.add_argument("--months", type=int,
                        help="instead of --since/--until, fetch the most recent N months")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"concurrent in-flight fixture requests (default {DEFAULT_CONCURRENCY})")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and re-fetch every month")
    parser.add_argument("--no-resolve", action="store_true",
                        help="skip entity resolution after fetching")
    parser.add_argument("--leagues",
                        help="comma-separated league ids to fetch (default: all). Season "
                             "depth varies hugely — the UEFA cups expose ~27 seasons back "
                             "to 2000 while domestic leagues expose 3 — so a deep --since "
                             "should target the deep leagues instead of spending thousands "
                             "of calls on windows that cannot contain data")
    args = parser.parse_args(argv)

    windows = (months.recent_windows(args.months) if args.months
               else months.windows_between(args.since, args.until))
    if not windows:
        print("! empty date range — nothing to fetch")
        return 1

    client = make_client("backfill")
    if client is None:
        return 1
    leagues = paths.load_leagues()
    if args.leagues:
        wanted = {int(part) for part in args.leagues.split(",") if part.strip()}
        leagues = [league for league in leagues if league["id"] in wanted]
        unknown = wanted - {league["id"] for league in leagues}
        if unknown:
            # Loudly, not silently: a typo'd id would otherwise just narrow the
            # run and look like a successful smaller backfill.
            print(f"! not in the league reference file, ignoring: {sorted(unknown)}")
        if not leagues:
            print("! no matching leagues — nothing to fetch")
            return 1

    print(f"backfilling {len(leagues)} leagues x {len(windows)} months "
          f"({windows[0][0][:7]} .. {windows[-1][0][:7]}), concurrency={args.concurrency}")

    run_fetch(client, leagues, windows, args.concurrency, args.refresh)
    if not args.no_resolve:
        resolve.run(client, args.concurrency)
    print(f"\nquota remaining by entity: {client.quota_snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
