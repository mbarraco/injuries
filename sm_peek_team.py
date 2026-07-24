#!/usr/bin/env python3
"""Peek at one cached team record's fields."""
import glob
import json

files = glob.glob("/Users/mbarraco/code/injuries/data/raw/sportmonks/teams/*.json")
print(f"{len(files)} cached team files")
with open(files[0], encoding="utf-8") as f:
    d = json.load(f)
print(json.dumps(d, indent=2)[:1200])
