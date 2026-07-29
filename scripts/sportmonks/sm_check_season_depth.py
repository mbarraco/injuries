#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""How many seasons per league does the plan actually expose — right now?

The fixture cache holds almost no domestic data before 2024, and the reason
turned out to be season access, not a bad query path: on the pre-upgrade plan
`/leagues/{id}?include=seasons` listed only 2024/25, 2025/26 and 2026/27 for
England, Spain and Italy. `/fixtures/between` can only ever return fixtures
from seasons the plan includes, so older windows come back legitimately empty.

That measurement is from the CACHED seasons files, which predate the
2026-07-27 subscription upgrade. This re-asks the API live, so the conclusion
isn't drawn from stale data. If the upgrade widened season access, the
backfill can reach much further back and it's worth re-running immediately.

Refreshes data/raw/sportmonks/seasons/{league_id}.json as it goes. Costs one
League-bucket call per league (~62), which is cheap and non-competing with the
Fixture/Player buckets.

Usage:
    uv run python scripts/sm_check_season_depth.py
    uv run python scripts/sm_check_season_depth.py --no-write
"""
import argparse
import json
import os

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOOTBALL = "https://api.sportmonks.com/v3/football"
SEASONS_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "seasons")
LEAGUES_CACHE = os.path.join(BASE, "data", "raw", "sportmonks", "leagues.json")
COVERAGE_FILE = os.path.join(BASE, "data", "reference", "sportmonks",
                             "coverage_uefa55.json")

# What the cached (pre-upgrade) files showed for the big domestic leagues, so
# the output can say "wider now" rather than leaving you to remember.
BASELINE_DOMESTIC_SEASONS = 3

# Earliest month the backfill has actually run with (its --since default). A
# league is only worth a deeper pass if it exposes seasons older than this.
BACKFILLED_SINCE_YEAR = "2014"


def load_leagues():
    """(id, name) for every league we'd want season depth on."""
    if os.path.exists(LEAGUES_CACHE):
        with open(LEAGUES_CACHE, encoding="utf-8") as handle:
            return [(row["id"], row.get("name", "?")) for row in json.load(handle) if row.get("id")]
    with open(COVERAGE_FILE, encoding="utf-8") as handle:
        leagues = json.load(handle).get("leagues", [])
    return [(row["id"], row.get("league", "?")) for row in leagues if row.get("id")]


def main():
    parser = argparse.ArgumentParser(description="Measure season depth per league")
    parser.add_argument("--no-write", action="store_true",
                        help="probe only; don't refresh the cached seasons files")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    leagues = load_leagues()
    print(f"checking season depth for {len(leagues)} leagues (League bucket) …\n")
    if not args.no_write:
        os.makedirs(SEASONS_DIR, exist_ok=True)

    results, failed = [], []
    for league_id, name in leagues:
        response = requests.get(f"{FOOTBALL}/leagues/{league_id}",
                                params={"api_token": token, "include": "seasons"}, timeout=30)
        if response.status_code != 200:
            failed.append((league_id, name, response.status_code))
            continue
        data = (response.json() or {}).get("data") or {}
        seasons = data.get("seasons") or []
        years = sorted({(season.get("name") or "?")[:4] for season in seasons})
        results.append((league_id, name, len(seasons), years))
        if not args.no_write and data:
            with open(os.path.join(SEASONS_DIR, f"{league_id}.json"), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)

    results.sort(key=lambda row: -row[2])
    print(f"{'league':38} {'seasons':>7}  earliest..latest")
    print("-" * 78)
    for _, name, count, years in results:
        span = f"{years[0]}..{years[-1]}" if years else "-"
        print(f"  {name:36.36} {count:7}  {span}")

    if failed:
        print(f"\n{len(failed)} league(s) failed: {failed[:5]}")

    # Compare each league against the earliest month already backfilled, not
    # against a season count: what matters is whether it exposes seasons OLDER
    # than we've fetched, which is the only thing a deeper --since can win.
    deeper = [row for row in results if row[3] and row[3][0] < BACKFILLED_SINCE_YEAR]
    print("\n" + "=" * 78)
    if deeper:
        earliest = min(row[3][0] for row in deeper)
        ids = ",".join(str(row[0]) for row in sorted(deeper, key=lambda r: r[3][0]))
        print(f"VERDICT: {len(deeper)}/{len(results)} leagues expose seasons earlier than "
              f"{BACKFILLED_SINCE_YEAR}, the earliest month backfilled so far:")
        for league_id, name, _, years in sorted(deeper, key=lambda row: row[3][0]):
            print(f"    id={league_id:<6} {name:34.34} from {years[0]}")
        print(f"\n  -> Fetch that history. Target these ids explicitly: a blanket deep")
        print(f"     --since would also re-scan every 3-season league across ~{len(results) - len(deeper)}")
        print(f"     leagues x years of windows that cannot contain data.")
        print(f"       uv run python -m ingest.backfill --since {earliest}-01 "
              f"--until {int(BACKFILLED_SINCE_YEAR) - 1}-12 --leagues {ids}")
    else:
        print(f"VERDICT: no league exposes seasons earlier than {BACKFILLED_SINCE_YEAR}.")
        print("  -> Nothing deeper to fetch; the existing backfill window already covers")
        print("     everything the plan sells. Don't spend quota re-trying older windows.")

    shallow = [row for row in results if row[2] <= BASELINE_DOMESTIC_SEASONS]
    print(f"\n  {len(shallow)}/{len(results)} leagues expose only "
          f"<={BASELINE_DOMESTIC_SEASONS} seasons — for those, pre-{BACKFILLED_SINCE_YEAR} "
          f"history is a plan limit, not a fetching problem.")
    print("=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
