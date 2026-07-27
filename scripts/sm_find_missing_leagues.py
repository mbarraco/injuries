#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Which in-plan leagues are we NOT backfilling?

The backfill's league list is a static reference file (53 domestic UEFA
leagues) written before the subscription changed. This asks the API what the
token can actually see now, diffs it against that file, and prints the gap —
so newly-unlocked competitions (UEFA club competitions, extra divisions) don't
sit invisible.

Also caches the full league list to data/raw/sportmonks/leagues.json, which
the reference file never was: a durable record of what the plan exposed, kept
alongside the rest of the raw cache.

Costs one League-bucket call (plus pagination), so it's effectively free.

Usage:
    uv run python scripts/sm_find_missing_leagues.py
"""
import json
import os

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOOTBALL = "https://api.sportmonks.com/v3/football"
COVERAGE_FILE = os.path.join(BASE, "data", "sportmonks_coverage_uefa55.json")
LEAGUES_CACHE = os.path.join(BASE, "data", "raw", "sportmonks", "leagues.json")


def fetch_all_leagues(token):
    """Every league visible to this token, following pagination."""
    leagues, page = [], 1
    while True:
        response = requests.get(
            f"{FOOTBALL}/leagues",
            params={"api_token": token, "include": "country", "per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        leagues.extend(body.get("data") or [])
        if not (body.get("pagination") or {}).get("has_more"):
            return leagues
        page += 1


def main():
    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    print("fetching every league this token can see (League entity) …")
    leagues = fetch_all_leagues(token)
    os.makedirs(os.path.dirname(LEAGUES_CACHE), exist_ok=True)
    with open(LEAGUES_CACHE, "w", encoding="utf-8") as handle:
        json.dump(leagues, handle, ensure_ascii=False, indent=2)
    print(f"  {len(leagues)} leagues visible · cached -> {LEAGUES_CACHE}")

    with open(COVERAGE_FILE, encoding="utf-8") as handle:
        backfilled = {entry["id"] for entry in json.load(handle).get("leagues", [])}
    print(f"  {len(backfilled)} leagues in the backfill reference file\n")

    missing = [league for league in leagues if league.get("id") not in backfilled]
    if not missing:
        print("Nothing missing — the backfill covers every visible league.")
        return 0

    print("=" * 78)
    print(f"VISIBLE BUT NOT BACKFILLED — {len(missing)} league(s)")
    print("=" * 78)
    for league in sorted(missing, key=lambda item: item.get("id", 0)):
        country = (league.get("country") or {}).get("name", "?")
        print(f"  id={league.get('id'):<6} {league.get('name', '?'):38} "
              f"country={country:16} sub_type={league.get('sub_type', '?')}")

    print(f"\nTo backfill these, add their ids to {os.path.relpath(COVERAGE_FILE, BASE)}")
    print("and re-run:  uv run python -m ingest.backfill --since 2014-01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
