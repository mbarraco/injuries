#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Does the PLAYER-level `sidelined` include carry history, or only open cases?

Every absence we hold was reconstructed from fixtures, so our injury history
can only be as deep as our fixture history — and the plan caps domestic
fixtures at ~3 seasons. If a player's own `sidelined` include returns their
full career of absences instead, it would reach injuries from seasons whose
fixtures we can't fetch at all, which is the one route back to pre-2024
domestic history.

Worth testing carefully rather than assuming: the logbook (2026-07-23) records
that the TEAM-level `sidelined` include returns only currently-open absences,
which made it look like no archive existed. Player-level may behave the same.

For a few sampled players this reports how many absences come back, their date
range, how many are closed (`completed`), and how many are ids we do NOT
already have from fixtures — the last number is the actual payoff. Costs one
Player-bucket call per sampled player (default 5).

Usage:
    uv run python scripts/sm_probe_player_sidelined.py
    uv run python scripts/sm_probe_player_sidelined.py --sample 12
"""
import argparse
import glob
import json
import os
from collections import defaultdict

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOOTBALL = "https://api.sportmonks.com/v3/football"
FIXTURES_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "fixtures")


def absences_we_already_have():
    """sideline ids per player, as reconstructed from the fixture cache."""
    by_player = defaultdict(set)
    for path in glob.glob(os.path.join(FIXTURES_DIR, "*.json")):
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        for fixture in document.get("fixtures") or []:
            for pivot in fixture.get("sidelined") or []:
                sideline = pivot.get("sideline") or {}
                player_id = sideline.get("player_id") or pivot.get("player_id")
                sideline_id = pivot.get("sideline_id") or sideline.get("id")
                if player_id and sideline_id:
                    by_player[player_id].add(sideline_id)
    return by_player


def api_message(response):
    """The API's own error text, which distinguishes a bad include from a bad id."""
    try:
        body = response.json() or {}
    except ValueError:
        return response.text[:120]
    return str(body.get("message") or body.get("error") or body)[:120]


def resolve_include(token, player_id):
    """Which sidelined include does the PLAYER endpoint accept? None if neither.

    Reports what each candidate did instead of failing silently — a 404 here
    means 'wrong include shape', not 'player does not exist', and confusing the
    two is what made an earlier run look like a finding when it was a bug.
    """
    for candidate in ("sidelined.sideline", "sidelined"):
        response = requests.get(f"{FOOTBALL}/players/{player_id}",
                                params={"api_token": token, "include": candidate}, timeout=30)
        if response.status_code == 200:
            print(f"  include={candidate!r:22} HTTP 200  -> using this")
            return candidate
        print(f"  include={candidate!r:22} HTTP {response.status_code}  {api_message(response)}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Probe player-level sidelined depth")
    parser.add_argument("--sample", type=int, default=5,
                        help="how many players to probe (default 5; one call each)")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    print("indexing absences already held from fixtures …")
    known = absences_we_already_have()
    if not known:
        print("! fixture cache holds no absences — run a backfill first")
        return 1

    # Probe players we already have plenty of absences for: if the include is
    # current-only, a player with a rich fixture-derived history is exactly
    # where the shortfall shows up most clearly.
    sample = sorted(known, key=lambda pid: -len(known[pid]))[:args.sample]

    # `sidelined.sideline` is the correct nesting on a FIXTURE, where `sidelined`
    # is a pivot wrapping a `sideline` object — but the player endpoint 404s on
    # it, so the nesting evidently differs there. Try the plain include too
    # rather than assuming which one this endpoint wants.
    include = resolve_include(token, sample[0])
    if include is None:
        print("! no candidate include worked on the player endpoint — see errors above.")
        print("  Cannot conclude anything about player-level sidelined depth from this.")
        return 1
    print(f"using include={include!r}\n")

    print(f"probing {len(sample)} players (Player bucket)\n")
    print(f"{'player':>10} {'from_api':>9} {'in_cache':>9} {'NEW':>5} {'closed':>7}  date range")
    print("-" * 74)

    total_new, ok_count = 0, 0
    for player_id in sample:
        response = requests.get(f"{FOOTBALL}/players/{player_id}",
                                params={"api_token": token, "include": include},
                                timeout=30)
        if response.status_code != 200:
            print(f"{player_id:>10}  HTTP {response.status_code}  {api_message(response)}")
            continue
        ok_count += 1
        data = (response.json() or {}).get("data") or {}
        records = data.get("sidelined") or []

        ids, dates, closed = set(), [], 0
        for pivot in records:
            sideline = pivot.get("sideline") or {}
            sideline_id = pivot.get("sideline_id") or sideline.get("id")
            if sideline_id:
                ids.add(sideline_id)
            if sideline.get("start_date"):
                dates.append(sideline["start_date"][:10])
            if sideline.get("completed"):
                closed += 1

        new = ids - known[player_id]
        total_new += len(new)
        span = f"{min(dates)} .. {max(dates)}" if dates else "-"
        print(f"{player_id:>10} {len(ids):>9} {len(known[player_id]):>9} "
              f"{len(new):>5} {closed:>7}  {span}")

    print("\n" + "=" * 74)
    if not ok_count:
        # Never state a conclusion when nothing succeeded: "no new absences" and
        # "no responses at all" produce the same zero, and only one of them is
        # evidence about the API.
        print("VERDICT: INCONCLUSIVE — every request failed, so this says nothing about")
        print("whether player-level sidelined carries history. Fix the errors above and")
        print("re-run before deciding anything.")
    elif total_new:
        print(f"VERDICT: the player include returned {total_new} absence(s) our fixture")
        print("reconstruction does NOT have. It carries history beyond our fixture window —")
        print("worth a full pass over the player cache to widen the absence table.")
    else:
        print("VERDICT: every absence returned is one we already hold from fixtures.")
        print("The include adds no new records (consistent with the team-level include")
        print("being open-cases-only, logbook 2026-07-23). Don't spend a full pass on it.")
    print("Check the date ranges above too: if they stop at our fixture window, the")
    print("include is season-gated the same way fixtures are.")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
