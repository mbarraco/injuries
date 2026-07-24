#!/usr/bin/env python3
"""Diagnostic: is data/raw/sportmonks/fixtures/271_2024-03.json (Denmark,
March 2024) a stale file left over from the very first, pre-bugfix sweep
attempt? Compares its content against the 71 sidelined entries sm_deep.py
independently found for that exact month using the validated raw-pivot-
count method."""
import json
import os

path = os.path.join(os.path.dirname(__file__), "data", "raw", "sportmonks",
                    "fixtures", "271_2024-03.json")

with open(path, encoding="utf-8") as f:
    doc = json.load(f)

print(f"file: {path}")
print(f"fetched_at: {doc.get('fetched_at')}")
print(f"window: {doc.get('window')}")
print(f"truncated: {doc.get('truncated')}")

fixtures = doc.get("fixtures", [])
total_sidelined = sum(len(fx.get("sidelined") or []) for fx in fixtures)
print(f"fixtures: {len(fixtures)}")
print(f"total sidelined entries (raw pivot count): {total_sidelined}")
print(f"\nExpected from sm_deep.py's earlier, independently-verified probe: 71")
print("MATCH" if total_sidelined == 71 else "MISMATCH — this file is likely stale/wrong")
