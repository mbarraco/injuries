#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Probe: which leagues — grouped by confederation — does our plan actually see?

Answers "can we get matches for confederations beyond UEFA?" with real numbers
instead of speculation. The `/leagues` list is subscription-filtered (out-of-plan
leagues never appear, and there's no error — see logbook/sportmonks.md), so what
this prints IS what the current token can fetch fixtures/matches for.

Uses the League entity, whose hourly quota bucket is separate from Fixture, so
running this never competes with a backfill.

Mechanism:
  1. GET /football/leagues?include=country  (paginated) — every visible league.
  2. Map each league's country -> continent_id (from the include, falling back
     to the cached data/raw/sportmonks/countries.json), and continent_id -> a
     readable name via /core/continents (fetched once, best-effort).
  3. Print league counts per confederation, with a few examples each.

Continent is a close PROXY for confederation — Europe=UEFA, South America=
CONMEBOL, Africa=CAF, Asia=AFC, North America=CONCACAF, Oceania=OFC — not an
exact map (e.g. Australia is geographically Oceania but plays in AFC).

Usage:
    uv run python scripts/sm_leagues_by_confederation.py
"""
import json
import os
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
CORE = "https://api.sportmonks.com/v3/core"
HERE = os.path.dirname(os.path.abspath(__file__))
COUNTRIES_CACHE = os.path.join(HERE, "..", "data", "raw", "sportmonks", "countries.json")


def get_all(token, url, params=None, max_pages=50):
    """Paginate a list endpoint, waiting out a 429 if the bucket runs dry."""
    out, page = [], 1
    while page <= max_pages:
        query = {"api_token": token, "per_page": 100, "page": page}
        query.update(params or {})
        response = requests.get(url, params=query, timeout=30)
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After") or 30)
            print(f"  429 — waiting {wait}s for the quota window to reset …")
            time.sleep(wait)
            continue
        if response.status_code != 200:
            print(f"  ! HTTP {response.status_code} on {url} page {page}: {response.text[:150]}")
            break
        body = response.json()
        out.extend(body.get("data") or [])
        if not (body.get("pagination") or {}).get("has_more"):
            break
        page += 1
    return out


def load_continent_names(token):
    """continent_id -> name. Best-effort: numeric ids are used if unavailable."""
    data = get_all(token, f"{CORE}/continents")
    return {continent["id"]: continent["name"] for continent in data if continent.get("id")}


def load_cached_country_continents():
    """id -> continent_id from the countries we already cached, as a fallback
    for when the league's country include doesn't carry continent_id inline."""
    if not os.path.exists(COUNTRIES_CACHE):
        return {}
    with open(COUNTRIES_CACHE, encoding="utf-8") as handle:
        countries = json.load(handle)
    return {country["id"]: country.get("continent_id") for country in countries}


def main():
    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    print("fetching every league this token can see (League entity) …")
    leagues = get_all(token, f"{FOOTBALL}/leagues", {"include": "country"})
    print(f"  {len(leagues)} leagues visible to this subscription\n")
    if not leagues:
        print("No leagues returned — token/plan issue? See scripts/sm_check_plan.py.")
        return 1

    cached_continents = load_cached_country_continents()
    continent_names = load_continent_names(token)

    by_confederation = defaultdict(list)
    for league in leagues:
        country = league.get("country") or {}
        continent_id = country.get("continent_id") or cached_continents.get(country.get("id"))
        name = continent_names.get(continent_id) or (
            f"continent {continent_id}" if continent_id else "unknown")
        by_confederation[name].append(f"{league.get('name')} ({country.get('name', '?')})")

    print("Leagues available per confederation (continent proxy):")
    for confederation in sorted(by_confederation, key=lambda key: -len(by_confederation[key])):
        examples = by_confederation[confederation]
        print(f"\n  {confederation}: {len(examples)} leagues")
        for label in examples[:8]:
            print(f"    - {label}")
        if len(examples) > 8:
            print(f"    … and {len(examples) - 8} more")

    print(f"\nTOTAL: {len(leagues)} leagues across {len(by_confederation)} confederation(s).")
    if len(by_confederation) <= 1:
        print("Only one confederation is visible — the current plan doesn't expose")
        print("others. Getting them means adding those leagues to the subscription;")
        print("the backfill itself is already league-id-driven, so no code change is")
        print("needed once they're in-plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
