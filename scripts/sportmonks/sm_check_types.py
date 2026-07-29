#!/usr/bin/env python3
"""Check whether player position_ids resolve via our already-cached
types.json, or whether a separate reference endpoint is needed."""
import json

with open("/Users/mbarraco/code/injuries/data/raw/sportmonks/types.json", encoding="utf-8") as f:
    types = json.load(f)

by_id = {t["id"]: t for t in types}
for tid in (25, 148, 5, 11):  # position_id, detailed_position_id, two country_ids seen
    t = by_id.get(tid)
    print(f"id {tid}: {t if t else 'NOT in types.json'}")
