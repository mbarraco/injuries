"""Measure what the cached API-Football injury data actually contains.

Read-only and offline — reads `data/raw/apifootball/injuries/` and makes no API
calls. Answers the questions slice 6's schema depends on:

1. **How many rows, and how many real absences?** Each row is one player
   missing one fixture (`type: "Missing Fixture"`); a multi-match absence
   contributes one row per match. Unlike Sportmonks there is **no spell id**,
   so real absences can only be *inferred* — and this script measures how much
   that inference depends on an arbitrary choice, rather than reporting one
   confident number.
2. **What are the `type` and `reason` domains?** Only `"Missing Fixture"` has
   been observed; the vendor may use others. `reason` is free text and mixes
   injuries with suspensions.
3. **How much cross-competition duplication is there?** A player injured in
   March misses both his domestic and his European fixtures, so the *same*
   absence appears in two different league feeds. Any dedup keyed on league
   would miss this — the key must be the player.

The headline output is a **sensitivity table**, not a single figure. If the
inferred absence count swings wildly with the gap threshold, spell
reconstruction is too fragile to build on, and the schema should store the
vendor's own fixture-appearance grain and treat spells as a clearly-labelled
derived view.

Usage:
    uv run python scripts/apifootball/af_measure_grain.py
    uv run python scripts/apifootball/af_measure_grain.py --reasons 40
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INJURIES_DIR = os.path.join(BASE, "data", "raw", "apifootball", "injuries")

# Gap thresholds (days) for collapsing a player's consecutive missed fixtures
# into one absence. Reported as a range on purpose: there is no vendor-supplied
# boundary, so the honest output is how much the answer moves.
GAP_THRESHOLDS = [7, 14, 30, 60, 120]

# Reason strings that are plainly not injuries. Matched case-insensitively as
# substrings; deliberately conservative — anything unmatched counts as
# "other/unclassified" and is reported, never silently folded into "injury".
NON_INJURY_MARKERS = ("suspend", "red card", "yellow card", "national team",
                      "national selection", "international duty", "inactive",
                      "lacking match fitness", "personal reason", "rest",
                      "coach's decision", "not in squad", "transfer", "doping")

# `type` values observed in the real data. "Questionable" is a DOUBT, not an
# absence — the player may well have played. Counting it as an absence
# overstates the total by ~13%.
CONFIRMED_ABSENCE = "Missing Fixture"


def load_rows():
    """Every cached injury row, flattened. Returns (rows, files, empty_files)."""
    rows, files, empty = [], 0, 0
    for path in sorted(glob.glob(os.path.join(INJURIES_DIR, "*.json"))):
        files += 1
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        records = document.get("injuries") or []
        if not records:
            empty += 1
        for record in records:
            player = record.get("player") or {}
            team = record.get("team") or {}
            fixture = record.get("fixture") or {}
            league = record.get("league") or {}
            rows.append({
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "type": player.get("type"),
                "reason": player.get("reason"),
                "team_id": team.get("id"),
                "fixture_id": fixture.get("id"),
                "fixture_date": fixture.get("date"),
                "league_id": league.get("id"),
                "league_name": league.get("name"),
                "season": league.get("season"),
            })
    return rows, files, empty


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def infer_absences(rows, gap_days):
    """Collapse rows into inferred absences.

    Grouped by **(player, reason)** — deliberately NOT including league or
    season. A single injury spans every competition the player misses, so a
    league-keyed grouping would double-count the same absence across a domestic
    league and a European cup. Within a group, fixtures sorted by date are cut
    into a new absence wherever the gap exceeds `gap_days`.
    """
    by_player_reason = defaultdict(list)
    undated = 0
    for row in rows:
        date = parse_date(row["fixture_date"])
        if date is None:
            undated += 1
            continue
        by_player_reason[(row["player_id"], (row["reason"] or "").lower())].append(date)

    absences = 0
    for dates in by_player_reason.values():
        dates.sort()
        absences += 1
        for previous, current in zip(dates, dates[1:]):
            if (current - previous).days > gap_days:
                absences += 1
    return absences, undated


def classify_reason(reason):
    lowered = (reason or "").lower()
    if not lowered:
        return "missing"
    for marker in NON_INJURY_MARKERS:
        if marker in lowered:
            return "non-injury"
    return "injury-ish"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure the grain of cached API-Football injury data")
    parser.add_argument("--reasons", type=int, default=25,
                        help="how many distinct reasons to list (default 25)")
    args = parser.parse_args(argv)

    if not os.path.isdir(INJURIES_DIR):
        print(f"! no cache at {INJURIES_DIR}\n"
              f"  Run: uv run python -m ingest.apifootball.injuries")
        return 1

    rows, files, empty_files = load_rows()
    if not rows:
        print(f"! {files} cached file(s) but no rows in them")
        return 1

    print(f"\n### Volume\n")
    print(f"  cached league-seasons : {files} ({empty_files} empty)")
    print(f"  rows (player-fixture) : {len(rows):,}")
    print(f"  distinct players      : {len({r['player_id'] for r in rows}):,}")
    print(f"  distinct teams        : {len({r['team_id'] for r in rows}):,}")
    print(f"  distinct fixtures     : {len({r['fixture_id'] for r in rows}):,}")
    print(f"  competitions          : {len({r['league_id'] for r in rows})}")

    # ---- type domain: only "Missing Fixture" has been observed so far ------ #
    types = Counter(r["type"] for r in rows)
    print(f"\n### `type` domain\n")
    for value, count in types.most_common():
        print(f"  {str(value):24} {count:>9,}  ({count / len(rows):.1%})")

    # ---- reason domain: free text, mixes injuries and non-injuries --------- #
    reasons = Counter((r["reason"] or "").strip() for r in rows)
    categories = Counter(classify_reason(r["reason"]) for r in rows)
    print(f"\n### `reason` — {len(reasons):,} distinct values\n")
    for value, count in reasons.most_common(args.reasons):
        print(f"  {value[:38]:38} {count:>9,}")
    if len(reasons) > args.reasons:
        print(f"  … and {len(reasons) - args.reasons:,} more distinct reasons")
    print(f"\n  rough split (substring match, conservative):")
    for value, count in categories.most_common():
        print(f"    {value:18} {count:>9,}  ({count / len(rows):.1%})")
    print("    NB: 'injury-ish' is everything not positively identified as a "
          "non-injury.\n        It is an upper bound on injuries, not a "
          "measurement of them.")

    # ---- cross-competition spread ----------------------------------------- #
    # Keyed on (player, reason), NOT (player, date): a player cannot appear in
    # two matches on the same day, so a date-keyed check is guaranteed to find
    # nothing and says nothing about duplication. The real question is whether
    # one absence spans fixtures in several competitions.
    spell_leagues = defaultdict(set)
    for row in rows:
        spell_leagues[(row["player_id"], (row["reason"] or "").lower())].add(
            row["league_id"])
    multi = sum(1 for leagues in spell_leagues.values() if len(leagues) > 1)
    print(f"\n### Cross-competition spread\n")
    print(f"  (player, reason) groups spanning >1 competition: {multi:,} "
          f"of {len(spell_leagues):,} "
          f"({multi / max(1, len(spell_leagues)):.1%})")
    print("  One absence keeps a player out of every competition his club is "
          "in, so these\n  are the SAME absence seen through several league "
          "feeds. Dedup must key on the\n  player, never the league — a "
          "league-keyed count inflates exactly the players\n  at the biggest "
          "clubs.")

    # ---- the sensitivity table — the point of the whole script ------------ #
    # Restricted to confirmed absences: a "Questionable" row records a doubt
    # about availability, not a missed match, and folding the two together
    # inflates every downstream count.
    confirmed = [r for r in rows if r["type"] == CONFIRMED_ABSENCE]
    print(f"\n### Inferred absences vs gap threshold\n")
    print(f"  Using the {len(confirmed):,} '{CONFIRMED_ABSENCE}' rows only; "
          f"{len(rows) - len(confirmed):,} 'Questionable'\n  rows excluded — a "
          f"doubt is not an absence.\n")
    print(f"  gap (days) | absences | rows per absence")
    print(f"  -----------|----------|-----------------")
    results = []
    for gap in GAP_THRESHOLDS:
        absences, undated = infer_absences(confirmed, gap)
        results.append(absences)
        print(f"  {gap:>10} | {absences:>8,} | {len(confirmed) / absences:>16.1f}")
    spread = (max(results) - min(results)) / max(1, min(results))
    print(f"\n  spread across thresholds: {spread:.0%}")
    if spread > 0.25:
        print("  -> The inferred count moves substantially with an arbitrary "
              "parameter.\n     Store the vendor's fixture-appearance grain as "
              "the source of truth and\n     treat any absence count as a "
              "derived estimate, labelled with its threshold.")
    else:
        print("  -> The inferred count is fairly stable across thresholds, so "
              "spell\n     reconstruction is defensible — still record which "
              "threshold produced it.")

    _absences, undated = infer_absences(rows, GAP_THRESHOLDS[0])
    if undated:
        print(f"\n  ! {undated:,} row(s) had no usable fixture date and were "
              f"excluded from the inference.")

    print("\nFor comparison, Sportmonks holds ~117,000 fixture-level mentions "
          "that dedupe\nto 26,408 distinct absences (~4.4 rows each) — but it "
          "supplies a real spell id,\nso that figure is measured, not inferred. "
          "Do not treat the two as equivalent.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
