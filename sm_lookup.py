#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Ad-hoc Sportmonks ID resolver — turn the internal IDs you find inside a
raw cache file (data/raw/sportmonks/fixtures/*.json) into readable names.

Fixture/sidelined records only carry player_id and type_id, not names — this
is the tool to resolve them when you want to actually identify who a record
is about, or what an injury/suspension type_id means (e.g. a "Knock" vs
something serious enough to be newsworthy).

Usage:
    python sm_lookup.py --player 49395
    python sm_lookup.py --player 49395 12345 --type 561 531
    python sm_lookup.py --type 561
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
CORE = "https://api.sportmonks.com/v3/core"
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

MIN_INTERVAL = 0.8
_state = {"last": 0.0, "log": None}


def log_response(url, params, resp):
    if not _state.get("log"):
        return
    safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:2000]}
    with open(_state["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "url": url, "params": safe, "status": resp.status_code, "body": body,
        }, ensure_ascii=False) + "\n")


def get(session, token, url, params=None, max_retries=3):
    p = {"api_token": token}
    p.update(params or {})
    elapsed = time.monotonic() - _state["last"]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    for attempt in range(max_retries + 1):
        r = session.get(url, params=p, timeout=30)
        _state["last"] = time.monotonic()
        log_response(url, p, r)
        if r.status_code != 429:
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        wait = min(30, 5 * (2 ** attempt))
        print(f"  429; waiting {wait}s")
        time.sleep(wait)
    return 429, None


def lookup_player(session, token, pid):
    status, body = get(session, token, f"{FOOTBALL}/players/{pid}")
    if status != 200:
        print(f"  player {pid}: HTTP {status}")
        return
    d = (body or {}).get("data") or {}
    name = d.get("display_name") or d.get("name") or "?"
    common = d.get("common_name")
    nat = d.get("nationality_id")
    dob = d.get("date_of_birth")
    print(f"  player {pid}: {name}"
          + (f" (\"{common}\")" if common and common != name else "")
          + (f" — born {dob}" if dob else "")
          + (f" — nationality_id {nat}" if nat else ""))


def lookup_type(session, token, tid):
    status, body = get(session, token, f"{CORE}/types/{tid}")
    if status != 200:
        print(f"  type {tid}: HTTP {status}")
        return
    d = (body or {}).get("data") or {}
    print(f"  type {tid}: {d.get('name')!r}  code={d.get('code')!r}  group={d.get('group')!r}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Resolve Sportmonks player/type IDs to names")
    ap.add_argument("--player", type=int, nargs="+", default=[], help="one or more player IDs")
    ap.add_argument("--type", type=int, nargs="+", default=[], help="one or more type IDs")
    args = ap.parse_args()

    if not args.player and not args.type:
        print("Nothing to look up — pass --player and/or --type with one or more IDs.")
        return 1

    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-lookup.{ts}.log")
    print(f"logging responses -> {_state['log']}")

    session = requests.Session()
    if args.player:
        print("\nPlayers:")
        for pid in args.player:
            lookup_player(session, token, pid)
    if args.type:
        print("\nTypes:")
        for tid in args.type:
            lookup_type(session, token, tid)
    return 0


if __name__ == "__main__":
    sys.exit(main())