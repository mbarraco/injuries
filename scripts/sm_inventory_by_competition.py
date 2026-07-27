#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Inventory: which competitions do we have in the fixture cache, and how much data?

Groups cached fixtures by competition/league name (not just league_id) and reports
fixture count + year range per competition. Useful for spotting gaps like missing
cup competitions or specific league seasons.

Usage:
    uv run python scripts/sm_inventory_by_competition.py
"""
import glob
import json
import os
from collections import defaultdict
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_ROOT = os.path.join(BASE, "data", "raw", "sportmonks")
FIXTURES_DIR = os.path.join(RAW_ROOT, "fixtures")

# league_id -> name. leagues.json is the API's own list (written by
# sm_find_missing_leagues.py) and is authoritative; the hand-maintained
# coverage reference file is the fallback for when it hasn't been fetched yet.
LEAGUES_CACHE = os.path.join(RAW_ROOT, "leagues.json")
COVERAGE_FILE = os.path.join(BASE, "data", "sportmonks_coverage_uefa55.json")

# Matched on id, not name: 'europa' as a substring also hits "Europa Conference
# League" and "UEFA Europa League Play-offs", which would make the status
# summary quietly wrong.
KEY_COMPETITIONS = {2: "Champions League", 5: "Europa League", 2286: "Conference League"}


def load_league_names():
    """Map league_id -> display name, preferring the API's own league list."""
    if os.path.exists(LEAGUES_CACHE):
        with open(LEAGUES_CACHE, encoding="utf-8") as handle:
            return {row["id"]: row.get("name", "?") for row in json.load(handle) if row.get("id")}
    if os.path.exists(COVERAGE_FILE):
        with open(COVERAGE_FILE, encoding="utf-8") as handle:
            leagues = json.load(handle).get("leagues", [])
        print(f"  ! {os.path.basename(LEAGUES_CACHE)} not found — falling back to the "
              f"coverage reference file. Run scripts/sm_find_missing_leagues.py to refresh.")
        return {row["id"]: f"{row.get('league', '?')} ({row.get('country', '?')})"
                for row in leagues if row.get("id")}
    print("  ! no league-name source found — showing raw ids")
    return {}


def main():
    # Scan all fixture files and group by league_id
    by_league = defaultdict(lambda: {"fixtures": 0, "years": set()})

    for path in glob.glob(os.path.join(FIXTURES_DIR, "*.json")):
        try:
            doc = json.load(open(path, encoding="utf-8"))
            league_id = doc.get("league_id")
            if league_id is None:
                continue
            fx = doc.get("fixtures") or []
            by_league[league_id]["fixtures"] += len(fx)

            # Extract year from filename: {league_id}_{year}-{month}.json
            basename = os.path.basename(path)
            if "_" in basename:
                year_month = basename.split("_")[1].split(".")[0]
                if "-" in year_month:
                    year = year_month.split("-")[0]
                    by_league[league_id]["years"].add(int(year))
        except (json.JSONDecodeError, KeyError):
            pass

    print("\n" + "=" * 80)
    print("FIXTURE CACHE INVENTORY BY COMPETITION")
    print("=" * 80 + "\n")
    league_names = load_league_names()

    # Only competitions that actually returned fixtures are worth listing — an
    # id with 0 fixtures is a cached-but-empty league, not a competition.
    stocked = {lid: data for lid, data in by_league.items() if data["fixtures"]}
    sorted_leagues = sorted(stocked.items(), key=lambda item: item[1]["fixtures"], reverse=True)
    print(f"{len(sorted_leagues)} leagues/competitions with cached fixtures\n")

    for league_id, data in sorted_leagues:
        league_name = league_names.get(league_id, f"[league_id {league_id}]")
        years = sorted(data["years"])
        year_range = f"{min(years)}-{max(years)}" if years else "?"
        marker = "* " if league_id in KEY_COMPETITIONS else "  "
        print(f"{marker}{league_name:40.40} {data['fixtures']:5} fixtures  ({year_range})")

    print("\n" + "=" * 80)
    print("KEY COMPETITIONS STATUS:")
    for league_id, key_name in sorted(KEY_COMPETITIONS.items(), key=lambda item: item[1]):
        fixtures = stocked.get(league_id, {}).get("fixtures", 0)
        status = f"OK  {fixtures} fixtures" if fixtures else "MISSING"
        print(f"  {key_name:20} {status}")

    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    main()
