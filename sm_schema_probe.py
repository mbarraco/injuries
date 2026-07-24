#!/usr/bin/env python3
"""Probe the raw fixture cache to confirm what a deduped injury record can
actually carry — informs the app schema design."""
import glob
import json
import os
from collections import Counter

BASE = os.path.dirname(__file__)
files = glob.glob(os.path.join(BASE, "data", "raw", "sportmonks", "fixtures", "*.json"))

by_sideline_id = {}
appearances = Counter()
league_of_sideline = {}
season_of_sideline = {}

for path in files:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    league_id = doc.get("league_id")
    for fx in doc.get("fixtures", []):
        for pivot in fx.get("sidelined") or []:
            sl = pivot.get("sideline") or {}
            sid = pivot.get("sideline_id") or sl.get("id")
            if not sid:
                continue
            appearances[sid] += 1
            if sid not in by_sideline_id and sl:
                by_sideline_id[sid] = sl
                league_of_sideline[sid] = league_id
                season_of_sideline[sid] = fx.get("season_id")

print(f"raw pivot rows scanned: {sum(appearances.values())}")
print(f"DISTINCT injuries (unique sideline_id): {len(by_sideline_id)}")
print(f"dedup ratio: {sum(appearances.values()) / max(len(by_sideline_id),1):.1f}x")

print("\nfield fill rates across distinct injuries:")
fields = ["player_id", "team_id", "type_id", "category", "season_id",
          "start_date", "end_date", "games_missed", "completed"]
n = len(by_sideline_id)
for fld in fields:
    filled = sum(1 for s in by_sideline_id.values() if s.get(fld) not in (None, ""))
    print(f"  {fld:15} {filled:6}/{n}  ({100*filled/max(n,1):.0f}%)")

print("\ncategory values:", Counter(s.get("category") for s in by_sideline_id.values()).most_common())
print(f"season_id derivable from parent fixture: "
      f"{sum(1 for v in season_of_sideline.values() if v)}/{n}")
print(f"league_id derivable from cache filename: "
      f"{sum(1 for v in league_of_sideline.values() if v)}/{n}")
