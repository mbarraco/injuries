#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Inventory probe: what does our UEFA plan actually expose per match & player?

Injuries are just one include on a fixture. This asks the broader question —
"which other includes/endpoints return real data on the current subscription?"
— and answers it with evidence instead of guesswork, because this API returns a
silent empty 200 for anything out of plan (see logbook/sportmonks.md).

For ONE real in-plan fixture and ONE real player (seeded from our existing
cache, so no discovery calls), it requests a set of candidate includes ONE AT A
TIME (so a single invalid include can't fail the whole batch) and reports, per
include: HTTP status, whether the include came back populated, and a peek at its
shape. Sample responses are cached under data/exploration/ — a SEPARATE folder
from the ingest cache (data/raw/…), so eyeballing shapes never pollutes the data
the ETL reads.

Fixture includes bill the Fixture bucket; player includes bill the Player
bucket — independent hourly quotas, so this is a couple dozen cheap calls.

Usage:
    uv run python scripts/sm_probe_includes.py
    uv run python scripts/sm_probe_includes.py --fixture 18535517 --player 14
    uv run python scripts/sm_probe_includes.py --no-cache
"""
import argparse
import glob
import json
import os
import re
import time

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES_CACHE = os.path.join(HERE, "..", "data", "raw", "sportmonks", "fixtures")
EXPLORE_DIR = os.path.join(HERE, "..", "data", "exploration", "includes")

# Candidate includes to test. Not exhaustive — a representative spread of the
# match- and player-level data worth knowing about. Edit freely to probe more.
FIXTURE_INCLUDES = [
    "participants", "scores", "events", "statistics", "lineups", "lineups.details",
    "formations", "referees", "venue", "weather", "odds", "sidelined.sideline",
    "periods", "state", "coaches",
]
PLAYER_INCLUDES = [
    "statistics", "statistics.details", "sidelined", "sidelined.sideline",
    "teams", "transfers", "trophies", "nationality", "position", "metadata", "latest",
]


def get(token, url, params=None, max_wait=90):
    """Single GET. On a 429 it waits out the bucket only if the reset is soon
    (<= max_wait seconds); otherwise it returns immediately with the
    Retry-After so the caller can skip rather than block on a full rolling-hour
    reset (which can be ~an hour). Returns (status, body); on a skipped 429 the
    body carries {"_retry_after": seconds}."""
    while True:
        query = {"api_token": token}
        query.update(params or {})
        response = requests.get(url, params=query, timeout=30)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After") or 30)
            if retry_after > max_wait:
                return 429, {"_retry_after": retry_after}
            print(f"    429 — waiting {retry_after}s for the bucket to reset …")
            time.sleep(retry_after)
            continue
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None


def seed_ids_from_cache():
    """Pull a real (fixture_id, player_id) pair out of the cached fixtures.

    Prefers a big league (England=8) so the fixture is data-rich, then any
    cached file. Returns (None, None) if the cache is empty.
    """
    files = sorted(glob.glob(os.path.join(FIXTURES_CACHE, "*.json")))
    files.sort(key=lambda path: not os.path.basename(path).startswith("8_"))
    fallback_fixture = None
    for path in files:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        for fixture in document.get("fixtures", []):
            fixture_id = fixture.get("id")
            if fixture_id and fallback_fixture is None:
                fallback_fixture = fixture_id  # usable for fixture includes even w/o a player
            for pivot in fixture.get("sidelined") or []:
                player_id = (pivot.get("sideline") or {}).get("player_id")
                if fixture_id and player_id:
                    return fixture_id, player_id
    return fallback_fixture, None


def _sanitize(name):
    return re.sub(r"[^0-9a-zA-Z]+", "_", name)


def describe(value):
    """A compact human note about what an include returned."""
    if value is None:
        return "absent / empty"
    if isinstance(value, list):
        return f"list[{len(value)}]" if value else "list[0] (empty)"
    if isinstance(value, dict):
        return f"object ({len(value)} keys)" if value else "object (empty)"
    return f"{type(value).__name__}={value!r}"[:40]


def probe(token, label, base_url, entity_id, includes, cache, max_wait):
    print(f"\n{'=' * 70}\n{label}  (id={entity_id})\n{'=' * 70}")
    if entity_id is None:
        print("  ! no id available to probe — skipping")
        return
    for include in includes:
        status, body = get(token, f"{base_url}/{entity_id}", {"include": include}, max_wait)
        if status == 429:
            resets = (body or {}).get("_retry_after")
            other = "player" if label == "fixture" else "fixture"
            print(f"  ! {label} bucket exhausted (resets in ~{resets}s). Skipping the "
                  f"rest of the {label} includes.\n    Re-run after the reset, or probe "
                  f"the other bucket now:  --only {other}")
            return
        data = (body or {}).get("data") or {}
        top_key = re.split(r"[.;]", include)[0]
        note = describe(data.get(top_key)) if status == 200 else "—"
        flag = "ok " if (status == 200 and data.get(top_key)) else "   "
        print(f"  {flag}{include:22} HTTP {status}   {note}")
        if cache and status == 200:
            os.makedirs(EXPLORE_DIR, exist_ok=True)
            out = os.path.join(EXPLORE_DIR, f"{_sanitize(label)}_{_sanitize(include)}.json")
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(body, handle, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Probe which includes our plan exposes")
    parser.add_argument("--fixture", type=int, help="fixture id to probe (default: from cache)")
    parser.add_argument("--player", type=int, help="player id to probe (default: from cache)")
    parser.add_argument("--only", choices=["fixture", "player"],
                        help="probe just one entity's bucket (e.g. --only player when the "
                             "Fixture bucket is spent from a backfill)")
    parser.add_argument("--max-wait", type=int, default=90,
                        help="max seconds to wait out a 429 before skipping that bucket "
                             "(default 90; a full rolling-hour reset can be ~3600)")
    parser.add_argument("--no-cache", action="store_true", help="don't save sample responses")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    fixture_id, player_id = args.fixture, args.player
    if fixture_id is None or player_id is None:
        seeded_fixture, seeded_player = seed_ids_from_cache()
        fixture_id = fixture_id or seeded_fixture
        player_id = player_id or seeded_player
    if fixture_id is None:
        print("! no fixture id (cache empty and none passed) — run a backfill first, "
              "or pass --fixture")
        return 1

    cache = not args.no_cache
    print(f"probing includes  (fixture={fixture_id}, player={player_id}, "
          f"cache={'on -> ' + EXPLORE_DIR if cache else 'off'})")
    if args.only != "player":
        probe(token, "fixture", f"{FOOTBALL}/fixtures", fixture_id, FIXTURE_INCLUDES,
              cache, args.max_wait)
    if args.only != "fixture":
        probe(token, "player", f"{FOOTBALL}/players", player_id, PLAYER_INCLUDES,
              cache, args.max_wait)

    print("\nLegend: 'ok' = include returned populated data on this plan. Empty/absent")
    print("means either no data for this sample, or the include isn't in-plan — the")
    print("API can't tell those apart, so treat a single empty as 'inconclusive, retry")
    print("on another sample' rather than 'unavailable'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
