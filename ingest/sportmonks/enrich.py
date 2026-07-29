"""Enrichment passes — re-fetch already-cached entities with richer includes.

The history backfill captured fixtures with only `sidelined.sideline`, and the
resolve step captured players with just their core fields. Both can be upgraded
*in place*: because Sportmonks bills one request per call regardless of how many
includes ride on it (rate-limits doc), a single richer re-fetch per entity
captures a whole match record / player-season stats at one charge each.

Resumable by design — an already-enriched cache file is detected and skipped, so
a run only pays for what's still on the thin include set. Players bill the
Player bucket and fixtures the Fixture bucket (independent hourly quotas), so the
two passes can run at the same time without competing.

Usage:
    python -m ingest.enrich --target players
    python -m ingest.enrich --target fixtures
    python -m ingest.enrich --target all
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from ingest.core import months
from ingest.core.cache import read_cache, write_cache
from ingest.sportmonks import paths
from ingest.sportmonks.backfill import (
    RICH_FIXTURE_INCLUDE, fetch_fixture_window, make_client)
from ingest.sportmonks.client import FIXTURE, PLAYER

# Everything useful the Player endpoint exposes in one call (probe-verified
# in-plan): per-season stats with their detail metrics (minutes, appearances,
# lineups → injury rate), career transfers, and team history.
PLAYER_INCLUDE = "statistics.details;transfers;teams"

_FIXTURE_FILE = re.compile(r"(\d+)_(\d{4}-\d{2})\.json$")


# --------------------------------------------------------------------------- #
# Enrichment predicates — pure, so the resumability logic is unit-testable
# without touching the network or the filesystem.
# --------------------------------------------------------------------------- #
def needs_player_enrich(document):
    """A cached player needs enrichment until it carries a `statistics` key.

    Presence (not truthiness) is the test: a player with a genuinely empty
    career still gets `statistics: []` once the include is requested, so keying
    on presence avoids re-fetching such players forever.
    """
    return "statistics" not in (document or {})


def needs_fixture_enrich(document):
    """A cached fixture-month needs enrichment if it holds fixtures but was
    fetched on the thin include set. Empty months carry nothing to enrich, so
    they're skipped — never re-fetched just to add includes to zero fixtures."""
    document = document or {}
    if not document.get("fixtures"):
        return False
    return "lineups" not in (document.get("include") or "")


# --------------------------------------------------------------------------- #
# Players.
# --------------------------------------------------------------------------- #
def enrich_players(client, concurrency):
    paths_todo = [path for path in glob.glob(os.path.join(paths.PLAYERS_DIR, "*.json"))
                  if needs_player_enrich(read_cache(path))]
    total = len(glob.glob(os.path.join(paths.PLAYERS_DIR, "*.json")))
    print(f"\nPLAYERS — {total} cached · {len(paths_todo)} need stats/transfers/teams")
    if not paths_todo:
        return 0
    client.await_quota(PLAYER)

    enriched = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_fetch_player, client, path): path for path in paths_todo}
        for done, future in enumerate(as_completed(futures), 1):
            if future.result():
                enriched += 1
            if done % 50 == 0 or done == len(paths_todo):
                print(f"\r  enriched {done}/{len(paths_todo)}", end="", flush=True)
    print(f"\n  {enriched}/{len(paths_todo)} players enriched")
    return enriched


def _fetch_player(client, path):
    player_id = os.path.splitext(os.path.basename(path))[0]
    status, body = client.get(f"{paths.FOOTBALL}/players/{player_id}",
                              {"include": PLAYER_INCLUDE})
    data = (body or {}).get("data")
    if status != 200 or not data:
        return False
    write_cache(path, data)
    return True


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #
def enrich_fixtures(client, concurrency):
    todo = []
    all_files = glob.glob(os.path.join(paths.FIXTURES_DIR, "*.json"))
    for path in all_files:
        match = _FIXTURE_FILE.search(os.path.basename(path))
        if match and needs_fixture_enrich(read_cache(path)):
            todo.append((int(match.group(1)), match.group(2)))
    print(f"\nFIXTURES — {len(all_files)} cached months · {len(todo)} to enrich "
          f"(non-empty & still thin)")
    if not todo:
        return 0
    client.await_quota(FIXTURE)

    enriched = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_enrich_fixture_month, client, league_id, year_month):
                   (league_id, year_month) for league_id, year_month in todo}
        for done, future in enumerate(as_completed(futures), 1):
            if future.result():
                enriched += 1
            if done % 25 == 0 or done == len(todo):
                print(f"\r  enriched {done}/{len(todo)} months", end="", flush=True)
    print(f"\n  {enriched}/{len(todo)} months enriched")
    return enriched


def _enrich_fixture_month(client, league_id, year_month):
    d1, d2 = months.window_for(*months.parse_ym(year_month))
    fixtures, _truncated, _from_cache = fetch_fixture_window(
        client, league_id, d1, d2, refresh=True, include=RICH_FIXTURE_INCLUDE)
    return fixtures is not None


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-fetch cached entities with richer includes")
    parser.add_argument("--target", choices=["players", "fixtures", "all"], default="all",
                        help="which cache to enrich (default all). Players and fixtures use "
                             "independent quota buckets, so running them as two separate "
                             "processes lets both buckets work in parallel.")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="concurrent in-flight requests (default 3)")
    args = parser.parse_args(argv)

    client = make_client("enrich")
    if client is None:
        return 1
    if args.target in ("players", "all"):
        enrich_players(client, args.concurrency)
    if args.target in ("fixtures", "all"):
        enrich_fixtures(client, args.concurrency)
    print(f"\nquota remaining by entity: {client.quota_snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
