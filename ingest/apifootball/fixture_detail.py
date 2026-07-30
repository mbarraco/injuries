"""Per-fixture detail — the long tail of the crawl.

Four endpoints, each addressed by a single fixture id:

| endpoint | what it adds | why it matters here |
|---|---|---|
| `/fixtures/players` | minutes, rating, per-player match stats | **the only source of minutes played** |
| `/fixtures/lineups` | XI, bench, formation, coach | who was available but unused |
| `/fixtures/events` | goals, cards, subs | injury-forced substitutions |
| `/fixtures/statistics` | possession, shots, fouls | match context |

**`players` is the one that unlocks analysis.** Injury *rates* need a
denominator — minutes played — and this is the only endpoint that supplies it.
Absence counts alone cannot distinguish a player who is injured often from one
who simply plays a great deal. The Sportmonks side already has this via player
season stats; without it the two datasets are not comparable on rates.

**This is a multi-day crawl.** ~40,000 fixtures x 4 endpoints ≈ 160,000 calls
at 7,500/day ≈ three weeks; `--endpoints players` alone is ~40,000 ≈ six days.
It is designed to be run repeatedly and interrupted freely: every fetch is
cached, the work list is recomputed from what is missing, and hitting the daily
quota is a clean stop rather than a failure.

Usage:
    python -m ingest.apifootball.fixture_detail --dry-run
    python -m ingest.apifootball.fixture_detail --endpoints players
    python -m ingest.apifootball.fixture_detail --endpoints players,lineups
    python -m ingest.apifootball.fixture_detail --endpoints all --max-calls 7000
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ingest.apifootball import paths
from ingest.apifootball.client import CACHEABLE_OUTCOMES, STOP_OUTCOMES
from ingest.apifootball.injuries import make_client
from ingest.core.cache import read_cache, write_cache

DEFAULT_CONCURRENCY = 4

ENDPOINTS = {
    "players":    {"path": "/fixtures/players",    "dir": paths.FIXTURE_PLAYERS_DIR},
    "lineups":    {"path": "/fixtures/lineups",    "dir": paths.FIXTURE_LINEUPS_DIR},
    "events":     {"path": "/fixtures/events",     "dir": paths.FIXTURE_EVENTS_DIR},
    "statistics": {"path": "/fixtures/statistics", "dir": paths.FIXTURE_STATS_DIR},
}

# Ordered by value, not alphabetically: an interrupted `all` run should have
# spent its quota on minutes played before match trivia.
ENDPOINT_ORDER = ("players", "lineups", "events", "statistics")


def cached_fixture_ids():
    """Every fixture id in the cached league-season fixtures files.

    Derived from the fixtures cache, so `crawl --target fixtures` must run
    first. Returns a sorted list so a run's ordering is stable and progress
    across days is comparable.
    """
    ids = set()
    for path in sorted(glob.glob(os.path.join(paths.FIXTURES_DIR, "*.json"))):
        document = read_cache(path) or {}
        for entry in document.get("fixtures") or []:
            fixture = (entry or {}).get("fixture") or {}
            if fixture.get("id"):
                ids.add(fixture["id"])
    return sorted(ids)


def missing_for(endpoint, fixture_ids):
    """Fixture ids not yet cached for one endpoint — the real work list."""
    directory = ENDPOINTS[endpoint]["dir"]
    return [fid for fid in fixture_ids
            if not os.path.exists(paths.fixture_path(directory, fid))]


def fetch_one(client, endpoint, fixture_id, stop):
    """Fetch one fixture's detail for one endpoint. Returns (count, outcome)."""
    if stop.is_set():
        return None, "skipped"
    spec = ENDPOINTS[endpoint]
    path = paths.fixture_path(spec["dir"], fixture_id)
    if os.path.exists(path):
        return None, "cached"

    status, body, outcome, detail = client.get(spec["path"], {"fixture": fixture_id})

    if outcome in STOP_OUTCOMES:
        stop.set()
        return None, outcome
    if outcome not in CACHEABLE_OUTCOMES:
        return None, outcome

    records = (body or {}).get("response") or []
    write_cache(path, {
        "fixture_id": fixture_id, "endpoint": endpoint, "outcome": outcome,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response": records,
    })
    return len(records), outcome


def run_endpoint(client, endpoint, fixture_ids, concurrency, stop, max_calls=None):
    """Crawl one endpoint across the fixtures still missing it."""
    todo = missing_for(endpoint, fixture_ids)
    if max_calls is not None:
        todo = todo[:max_calls]
    done_already = len(fixture_ids) - len(missing_for(endpoint, fixture_ids))
    print(f"\n{endpoint.upper()} — {len(todo):,} to fetch "
          f"({done_already:,}/{len(fixture_ids):,} already cached)")
    if not todo:
        return 0, Counter()

    outcomes, records = Counter(), 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(fetch_one, client, endpoint, fid, stop) for fid in todo]
        for done, future in enumerate(as_completed(futures), 1):
            count, outcome = future.result()
            outcomes[outcome] += 1
            if count:
                records += count
            if done % max(1, min(100, len(todo) // 50)) == 0 or done == len(todo):
                # `done` counts every completed future, including ones a stop
                # event turned into an instant "skipped" — so it hits 100% even
                # when most items never reached the network. Progress against
                # the whole dataset must use what was actually fetched.
                fetched_so_far = done - outcomes["skipped"]
                pct = 100 * (done_already + fetched_so_far) / max(1, len(fixture_ids))
                print(f"\r  {fetched_so_far:,}/{len(todo):,} this run "
                      f"({outcomes['skipped']:,} skipped after stop) · "
                      f"{pct:.1f}% of all fixtures · {records:,} records",
                      end="", flush=True)
    print()
    return len(todo) - outcomes["skipped"], outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description="API-Football per-fixture detail crawl")
    parser.add_argument("--endpoints", default="players",
                        help="comma-separated: players,lineups,events,statistics "
                             "or 'all' (default: players — the minutes denominator)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--max-calls", type=int,
                        help="cap calls PER ENDPOINT this run, to stay inside a "
                             "budget you want to share with other work")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the outstanding work, make no calls")
    args = parser.parse_args(argv)

    chosen = (list(ENDPOINT_ORDER) if args.endpoints == "all"
              else [e.strip() for e in args.endpoints.split(",") if e.strip()])
    unknown = [e for e in chosen if e not in ENDPOINTS]
    if unknown:
        print(f"! unknown endpoint(s): {unknown}. Known: {list(ENDPOINTS)}")
        return 1
    # Preserve value order regardless of how the user listed them.
    chosen = [e for e in ENDPOINT_ORDER if e in chosen]

    fixture_ids = cached_fixture_ids()
    if not fixture_ids:
        print("! no fixtures cached — run this first:\n"
              "  uv run python -m ingest.apifootball.crawl --target fixtures")
        return 1

    print(f"{len(fixture_ids):,} fixtures known from the fixtures cache")
    if args.dry_run:
        total = 0
        print()
        for endpoint in chosen:
            missing = len(missing_for(endpoint, fixture_ids))
            total += missing
            print(f"  {endpoint:12} {missing:>7,} outstanding "
                  f"({len(fixture_ids) - missing:,} cached)")
        print(f"\n  total calls: ~{total:,}  ≈ {total / 7500:.1f} day(s) at "
              f"7,500/day")
        print("  Interrupt freely — every fetch is cached and a re-run "
              "resumes from what is missing.")
        return 0

    client = make_client("fixture-detail")
    if client is None:
        return 1
    stop = threading.Event()

    for endpoint in chosen:
        fetched, outcomes = run_endpoint(client, endpoint, fixture_ids,
                                         args.concurrency, stop, args.max_calls)
        print(f"  outcomes: {dict(outcomes)}")
        if stop.is_set():
            print("\n! daily quota exhausted — stopping. Everything fetched is "
                  "cached;\n  re-run tomorrow to continue from exactly here.")
            break

    print(f"\nquota: {client.quota()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
