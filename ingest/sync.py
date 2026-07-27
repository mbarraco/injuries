"""Incremental fetch — top up the cache from each league's watermark onward.

Where `backfill` grabs a wide historical range, `sync` fetches only the
months a league hasn't been fetched through yet: from the month after its
watermark up to the current month. Normally that's a single trailing month,
so a routine re-run is cheap and safe to run any time (post-trial, on a paid
plan, whenever).

A league with no watermark yet (never backfilled) falls back to fetching
just the current month, rather than silently doing nothing — running
`backfill` first is still the way to get real history.

Scheduling this (cron, etc.) is intentionally left to the operator; sync
only makes re-running correct and quota-cheap.

Usage:
    python -m ingest.sync
    python -m ingest.sync --no-resolve
"""
from __future__ import annotations

import argparse
import sys

from ingest import backfill, months, paths, resolve


def windows_since_watermark(watermark, league_id, until_ym=None):
    """Monthly windows to fetch for one league to reach `until_ym`.

    Starts at the month after the stored watermark; if there is none, fetches
    just `until_ym` (the current month by default).
    """
    until_ym = until_ym or months.current_ym()
    mark = watermark.get(str(league_id))
    start_ym = months.next_ym(mark) if mark else until_ym
    return months.windows_between(start_ym, until_ym)


def run_sync(client, leagues, concurrency, until_ym=None):
    """Fetch each league's outstanding months, advancing the watermark."""
    until_ym = until_ym or months.current_ym()
    watermark = backfill.read_watermark()
    totals = {"fetched": 0, "cached": 0, "failed": 0}
    for index, league in enumerate(leagues, 1):
        league_id = league["id"]
        windows = windows_since_watermark(watermark, league_id, until_ym)
        if not windows:
            continue
        stats = backfill.fetch_league(client, league_id, windows, concurrency)
        for key in totals:
            totals[key] += stats[key]
        backfill.advance_watermark(watermark, league_id, stats["latest_ok"])
        backfill.write_watermark(watermark)
        print(f"  [{index:2}/{len(leagues)}] {league.get('country', '?'):24} "
              f"+{len(windows)}mo fetched={stats['fetched']} cached={stats['cached']} "
              f"failed={stats['failed']} watermark={watermark.get(str(league_id))}")
    print(f"\nsync totals: fetched={totals['fetched']} cached={totals['cached']} "
          f"failed={totals['failed']}")
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sportmonks incremental sync")
    parser.add_argument("--until", default=months.current_ym(),
                        help="latest month to sync to, YYYY-MM (default: current month)")
    parser.add_argument("--concurrency", type=int, default=backfill.DEFAULT_CONCURRENCY)
    parser.add_argument("--no-resolve", action="store_true",
                        help="skip entity resolution after fetching")
    args = parser.parse_args(argv)

    client = backfill.make_client("sync")
    if client is None:
        return 1
    leagues = paths.load_leagues()
    print(f"syncing {len(leagues)} leagues up to {args.until}")

    run_sync(client, leagues, args.concurrency, args.until)
    if not args.no_resolve:
        resolve.run(client, args.concurrency)
    print(f"\nquota remaining by entity: {client.quota_snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
