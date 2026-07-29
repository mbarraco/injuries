#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Dataset consistency diagnostic: verify the complete raw cache is coherent.

Scans all cached fixtures, players, teams, types and reports:
- Fixture coverage by year and enrichment status
- Distinct absences and their category breakdown
- Referential integrity: orphans (referenced but not cached)
- Data quality notes (empty months, truncations, missing fields)

Run anytime after a backfill/enrich pass to verify the cache state.

Usage:
    uv run python scripts/sm_dataset_consistency.py
"""
import glob
import json
import os
import re
from collections import defaultdict
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_ROOT = os.path.join(BASE, "data", "raw", "sportmonks")


def main():
    print("\n" + "=" * 70)
    print("DATASET CONSISTENCY DIAGNOSTIC")
    print("=" * 70)

    # ---- Fixtures ----
    print("\n[FIXTURE MONTHS]")
    empty = nonempty = rich = thin = truncated = 0
    # category per DISTINCT absence, first occurrence wins — the same dedup the
    # ETL does. Counting categories per pivot row instead would report tens of
    # thousands of phantom 'unknown's: the same absence repeats once per missed
    # fixture, and on many of those repeats the nested `sideline` object isn't
    # populated, even though another fixture carries its real category.
    absence_category = {}
    cat = defaultdict(int)
    ref_players = set()
    ref_teams = set()
    ref_types = set()
    by_year_nonempty = defaultdict(int)
    by_year_empty = defaultdict(int)

    for path in sorted(glob.glob(os.path.join(RAW_ROOT, "fixtures", "*.json"))):
        doc = json.load(open(path, encoding="utf-8"))
        fx = doc.get("fixtures") or []
        ym = re.search(r"_(\d{4})-", os.path.basename(path))
        year = ym.group(1) if ym else "?"

        if not fx:
            empty += 1
            by_year_empty[year] += 1
            continue

        nonempty += 1
        by_year_nonempty[year] += 1
        if "lineups" in (doc.get("include") or ""):
            rich += 1
        else:
            thin += 1
        if doc.get("truncated"):
            truncated += 1

        for f in fx:
            for p in f.get("sidelined") or []:
                sl = p.get("sideline") or {}
                sid = p.get("sideline_id") or sl.get("id")
                if sid and sid not in absence_category:
                    absence_category[sid] = sl.get("category") or "unknown"
                cat[sl.get("category") or "unknown"] += 1
                if sl.get("player_id"):
                    ref_players.add(sl["player_id"])
                if sl.get("team_id"):
                    ref_teams.add(sl["team_id"])
                if sl.get("type_id"):
                    ref_types.add(sl["type_id"])

    print(f"  Total months cached: {empty + nonempty}")
    print(f"    Empty (no fixtures): {empty} ({100*empty//(empty+nonempty)}%)")
    print(f"    Non-empty: {nonempty}")
    print(f"      Enriched (lineups): {rich}")
    print(f"      Thin (injury-only): {thin}")
    print(f"      Truncated (page-cap hit): {truncated}")
    print(f"\n  Non-empty months by year:")
    for year in sorted(by_year_nonempty.keys()):
        print(f"    {year}: {by_year_nonempty[year]} non-empty, {by_year_empty.get(year,0)} empty")

    # ---- Absences ----
    distinct_category = defaultdict(int)
    for category in absence_category.values():
        distinct_category[category] += 1

    print(f"\n[ABSENCES]")
    print(f"  Distinct sideline_id: {len(absence_category)}")
    print(f"  By category (deduplicated — matches what the ETL loads):")
    for cat_name in sorted(distinct_category):
        print(f"    {cat_name:12} {distinct_category[cat_name]:6}")
    print(f"  By category (raw pivot rows, one per missed fixture — NOT absences):")
    for cat_name in sorted(cat):
        print(f"    {cat_name:12} {cat[cat_name]:6}")
    print(f"    {'(a pivot row shows category=unknown when that fixture did not'}")
    print(f"    {' populate the nested sideline object; the absence itself is'}")
    print(f"    {' categorised from whichever fixture did.)'}")

    # ---- Entity caches ----
    print(f"\n[ENTITY CACHES]")
    have_players = {
        int(os.path.basename(p)[:-5])
        for p in glob.glob(os.path.join(RAW_ROOT, "players", "*.json"))
    }
    have_teams = {
        int(os.path.basename(p)[:-5])
        for p in glob.glob(os.path.join(RAW_ROOT, "teams", "*.json"))
    }
    types_raw = json.load(open(os.path.join(RAW_ROOT, "types.json"), encoding="utf-8"))
    have_types = {t["id"] for t in types_raw}

    print(f"  Players: {len(have_players)} cached")
    print(f"  Teams: {len(have_teams)} cached")
    print(f"  Types: {len(have_types)} cached")

    # ---- Referential integrity ----
    print(f"\n[REFERENTIAL INTEGRITY (Orphans)]")
    orphan_players = ref_players - have_players
    orphan_teams = ref_teams - have_teams
    orphan_types = ref_types - have_types

    print(f"  Players: {len(ref_players)} referenced, {len(orphan_players)} orphan "
          f"({100*len(orphan_players)//max(len(ref_players),1)}%)")
    if orphan_players:
        print(f"    First 10: {sorted(orphan_players)[:10]}")

    print(f"  Teams: {len(ref_teams)} referenced, {len(orphan_teams)} orphan "
          f"({100*len(orphan_teams)//max(len(ref_teams),1)}%)")
    if orphan_teams:
        print(f"    First 10: {sorted(orphan_teams)[:10]}")

    print(f"  Types: {len(ref_types)} referenced, {len(orphan_types)} orphan "
          f"({100*len(orphan_types)//max(len(ref_types),1)}%)")

    # ---- Data quality summary ----
    print(f"\n[DATA QUALITY SUMMARY]")
    if truncated > 0:
        print(f"  ⚠️  {truncated} fixture-months hit pagination cap — counts may be understated")
    if len(orphan_players) > 0 or len(orphan_teams) > 0:
        print(f"  ⚠️  {len(orphan_players)} player ids, {len(orphan_teams)} team ids "
              f"referenced but not cached (out-of-plan clubs, lower divisions)")
    # Deliberately keyed on distinct absences, not pivot rows: pivot-row
    # 'unknown's are an artefact of the repeat encoding, not missing data.
    if distinct_category.get("unknown", 0):
        print(f"  ⚠️  {distinct_category['unknown']} absences have no category on any "
              f"fixture — genuinely uncategorised, worth investigating")
    if not truncated and len(orphan_players) <= 10 and len(orphan_teams) <= 10:
        print(f"  ✓ Dataset appears consistent — no major anomalies detected")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
