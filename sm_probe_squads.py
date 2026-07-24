#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests>=2.31,<3", "python-dotenv>=1.0,<2"]
# ///
"""Probe for the correct squad endpoint/include syntax before committing to
a full 53-league fetch. Untested territory — we've proven `/teams/seasons/
{season_id}` lists teams for a season, but never fetched a full roster.
Tests several plausible patterns against one real team+season (Denmark) and
reports which ones return actual player-list data.
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
BASE = "https://api.sportmonks.com/v3/football"


def get(path, params=None):
    p = {"api_token": token}
    p.update(params or {})
    r = requests.get(f"{BASE}{path}", params=p, timeout=30)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


# 1. Find Denmark's current season id from our cached seasons lookup.
with open("data/sportmonks_seasons.json", encoding="utf-8") as f:
    seasons = json.load(f)["seasons"]
denmark_seasons = {sid: s for sid, s in seasons.items()
                   if s["country"] == "DENMARK"}
current = next((sid for sid, s in denmark_seasons.items() if s["is_current"]), None)
if not current:
    current = sorted(denmark_seasons.keys())[-1]
print(f"using Denmark season_id={current} ({denmark_seasons[current]['name']})")

# 2. Get one real team id for that season (proven pattern).
status, body = get(f"/teams/seasons/{current}")
teams = (body or {}).get("data", []) or []
if not teams:
    print(f"! could not get teams for season {current}: HTTP {status}")
    raise SystemExit(1)
team_id = teams[0]["id"]
team_name = teams[0]["name"]
print(f"using team {team_id} ({team_name})\n")

# 3. Try several plausible squad patterns.
candidates = [
    ("include=squad on /teams/{id}", f"/teams/{team_id}", {"include": "squad"}),
    ("include=activeSeasons.squads", f"/teams/{team_id}", {"include": "activeSeasons.squads"}),
    ("/squads/teams/{id}", f"/squads/teams/{team_id}", {}),
    ("/squads/seasons/{season}/teams/{id}", f"/squads/seasons/{current}/teams/{team_id}", {}),
]

for label, path, params in candidates:
    status, body = get(path, params)
    if status != 200:
        print(f"[{label}] HTTP {status}")
        continue
    data = body.get("data")
    if isinstance(data, dict):
        squad = data.get("squad") or data.get("activeSeasons") or []
        n = len(squad) if isinstance(squad, list) else "?"
        print(f"[{label}] HTTP 200, data is dict, squad-ish field length: {n}")
    elif isinstance(data, list):
        print(f"[{label}] HTTP 200, data is a LIST of {len(data)} items")
        if data:
            print(f"    sample keys: {list(data[0].keys())}")
    else:
        print(f"[{label}] HTTP 200, data={data!r}")
