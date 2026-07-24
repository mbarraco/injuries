#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests>=2.31,<3", "python-dotenv>=1.0,<2"]
# ///
"""Isolate and re-test ONE specific fixture query live, bypassing the cache
entirely, to check whether Denmark/March 2024 returning 0 fixtures was a
one-off glitch or a reproducible limitation. Prints the raw response so we
can see exactly what Sportmonks says right now."""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")

r = requests.get(
    "https://api.sportmonks.com/v3/football/fixtures/between/2024-03-01/2024-04-01",
    params={
        "api_token": token,
        "filters": "fixtureLeagues:271",
        "include": "sidelined.sideline",
        "per_page": 100,
        "page": 1,
    },
    timeout=30,
)
print(f"HTTP {r.status_code}")
body = r.json()
print("top-level keys:", list(body.keys()))
print("message (if any):", body.get("message"))
print("pagination:", body.get("pagination"))
data = body.get("data", [])
print(f"fixtures returned: {len(data)}")
if data:
    print("first fixture name/date:", data[0].get("name"), data[0].get("starting_at"))
else:
    print("\nFull raw body (fixtures list was empty):")
    print(json.dumps(body, indent=2)[:3000])
