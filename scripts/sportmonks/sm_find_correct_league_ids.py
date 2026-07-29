#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests>=2.31,<3", "python-dotenv>=1.0,<2"]
# ///
"""One-off: find the correct in-plan league ids for Georgia and Gibraltar.

data/reference/sportmonks/coverage_uefa55.json currently has:
  Georgia:   id 316  "Erovnuli Liga 2"  (confirmed 2nd tier, wrong)
  Gibraltar: id 1526 "Gibraltar Cup"    (confirmed a cup, not the league)

These were flagged wrong back when the league picker was corrected in
MySportmonks, but this reference file was never updated to match — every
script reading league ids from it (sweep, entity resolution, seasons) has
been silently querying the wrong, unsubscribed competition for these two
countries. This script lists every in-plan league for those two countries
so we can pick the correct id and fix the JSON file.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")

data, page = [], 1
while True:
    r = requests.get(
        "https://api.sportmonks.com/v3/football/leagues",
        params={"api_token": token, "per_page": 50, "page": page, "include": "country"},
        timeout=30,
    )
    body = r.json()
    batch = body.get("data", [])
    data.extend(batch)
    pag = body.get("pagination") or {}
    if not batch or not pag.get("has_more"):
        break
    page += 1

print(f"{len(data)} leagues in plan total\n")
for l in data:
    country = (l.get("country") or {}).get("name", "?")
    if country in ("Georgia", "Gibraltar"):
        print(f"  [{l.get('id')}] {l.get('name')} ({country})")
