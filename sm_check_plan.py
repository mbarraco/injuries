#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Quick check: how many leagues does the current SPORTMONKS token actually see?

Run this before sm_sweep55.py to confirm the Pro upgrade + league selection
have taken effect. Free plan / stale token -> ~4 leagues. Pro with 53 UEFA
leagues selected -> ~53+ leagues.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
if not token or token.startswith("REPLACE_"):
    print("! SPORTMONKS token not set in .env")
    raise SystemExit(1)

data = []
page = 1
while True:
    r = requests.get(
        "https://api.sportmonks.com/v3/football/leagues",
        params={"api_token": token, "per_page": 50, "page": page, "include": "country"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"HTTP {r.status_code} on page {page}: {r.text[:200]}")
        break
    body = r.json()
    batch = body.get("data", [])
    data.extend(batch)
    pag = body.get("pagination") or {}
    print(f"  page {page}: +{len(batch)} (pagination={pag})")
    if not batch or not pag.get("has_more"):
        break
    page += 1

print(f"\nHTTP 200 - {len(data)} leagues visible (across {page} page(s))")
for l in data:
    country = (l.get("country") or {}).get("name", "?")
    print(f"  - {l.get('name')} ({country})")

if len(data) <= 5:
    print("\nStill looks like the free plan (or a stale token).")
    print("Check MySportmonks: subscription active? league picker saved?")
    print("new api_token issued for Pro? .env updated with it?")
else:
    print(f"\nLooks like Pro is active with {len(data)} leagues selected.")
    print("Safe to run: uv run --python 3.14 sm_sweep55.py")
