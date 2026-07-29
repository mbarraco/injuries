#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Sportmonks deep-dive: three questions sm_explore.py left open.

  A. BACKFILL VIABILITY — do OLD fixtures carry `sidelined` data? The team-level
     include only returns currently-open absences, but if historical fixtures
     carry injury records then an archive exists and can be reconstructed.
     This is the real test of "can we get history at all?".

  B. TYPE TAXONOMY — sm_explore saw type_id 531 but /core/types returned only
     25 types. That is probably a pagination mistake on our side, not a thin
     taxonomy. Resolve it properly before judging record richness.

  C. GATING LEVEL — out-of-plan LEAGUES return empty. Are PLAYERS and TEAMS
     gated the same way, or can we reach entities from leagues we do not own?
     If entities are reachable, the coverage picture changes.

Usage:
    python sm_deep.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
CORE = "https://api.sportmonks.com/v3/core"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")

IN_PLAN = {271: "Superliga (Denmark)", 501: "Premiership (Scotland)"}

# In-season windows going back years. Danish/Scottish seasons run autumn->spring,
# so March is reliably mid-season.
WINDOWS = [
    ("2015-03-01", "2015-04-01"),
    ("2018-03-01", "2018-04-01"),
    ("2020-02-01", "2020-03-01"),
    ("2022-03-01", "2022-04-01"),
    ("2024-03-01", "2024-04-01"),
    ("2026-03-01", "2026-04-01"),
]

MIN_INTERVAL = 0.8
_state = {"last": 0.0, "log": None}


def log_response(url, params, resp, elapsed):
    if not _state.get("log"):
        return
    safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:4000]}
    with open(_state["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "url": url, "params": safe, "status": resp.status_code,
            "elapsed_s": round(elapsed, 3), "body": body,
        }, ensure_ascii=False) + "\n")


def get(session, token, url, params=None, max_retries=3):
    p = {"api_token": token}
    p.update(params or {})
    elapsed = time.monotonic() - _state["last"]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        r = session.get(url, params=p, timeout=30)
        _state["last"] = time.monotonic()
        log_response(url, p, r, _state["last"] - t0)
        if r.status_code != 429:
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        wait = min(30, 5 * (2 ** attempt))
        print(f"    429; waiting {wait}s")
        time.sleep(wait)
    return 429, None


def section(t):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


# --------------------------------------------------------------------------- #
# A. Backfill viability
# --------------------------------------------------------------------------- #
def probe_backfill(session, token):
    section("A. BACKFILL VIABILITY — do OLD fixtures carry `sidelined` data?")
    print("   If old windows return sidelined records, history is reconstructable.")
    print("   If only recent windows do, there is no archive to backfill.\n")
    oldest_sample = None
    for lid, name in IN_PLAN.items():
        print(f"   {name}")
        for d1, d2 in WINDOWS:
            # Nested includes resolve the pivot row into a full record:
            #   .sideline = absence detail, .player = who, .type = readable label
            status, body = get(session, token, f"{FOOTBALL}/fixtures/between/{d1}/{d2}",
                               {"filters": f"fixtureLeagues:{lid}",
                                "include": "sidelined.sideline;sidelined.player;sidelined.type"})
            if status != 200:
                print(f"      {d1} .. {d2}   HTTP {status}")
                continue
            fixtures = (body or {}).get("data", []) or []
            recs = [r for f in fixtures for r in (f.get("sidelined") or [])]
            done = sum(1 for r in recs if r.get("completed") is True)
            print(f"      {d1} .. {d2}   {len(fixtures):3} fixtures, "
                  f"{len(recs):4} sidelined ({done} completed)")
            if recs and oldest_sample is None and d1 < "2023":
                oldest_sample = (d1, recs[0])
        print()
    if oldest_sample:
        d1, rec = oldest_sample
        print(f"   SAMPLE from the {d1} window (proves historical records exist):")
        print("   " + json.dumps(rec, indent=2, ensure_ascii=False).replace("\n", "\n   "))
        # The decisive check: did the nested include actually resolve the pivot?
        resolved = [k for k in ("sideline", "player", "type") if rec.get(k)]
        if resolved:
            print(f"\n   NESTED INCLUDE WORKED — resolved: {', '.join(resolved)}")
            print("   => historical backfill will yield full records, not just pivots.")
        else:
            print("\n   ! Nested include did NOT resolve (still a bare pivot).")
            print("   => syntax needs fixing BEFORE starting the 14-day trial.")
    else:
        print("   No sidelined records found in any pre-2023 window.")
        print("   => No queryable injury archive; backfill is NOT possible.")


# --------------------------------------------------------------------------- #
# B. Type taxonomy, done properly
# --------------------------------------------------------------------------- #
def probe_types_properly(session, token):
    section("B. TYPE TAXONOMY — resolve properly (paginate; look up ids directly)")
    # 1) direct lookup of the id we actually saw
    for tid in (531, 13):
        status, body = get(session, token, f"{CORE}/types/{tid}")
        data = (body or {}).get("data") or {}
        print(f"   /core/types/{tid} -> HTTP {status} "
              f"name={data.get('name')!r} group={data.get('group')!r} "
              f"code={data.get('code')!r}")

    # 2) paginate the full type list rather than trusting one page
    total, page, seen = 0, 1, []
    while page <= 12:
        status, body = get(session, token, f"{CORE}/types",
                           {"page": str(page), "per_page": "100"})
        if status != 200:
            print(f"   /core/types page {page} -> HTTP {status}; stopping")
            break
        data = (body or {}).get("data", []) or []
        total += len(data)
        seen.extend(data)
        pag = (body or {}).get("pagination") or {}
        if not data or not pag.get("has_more"):
            break
        page += 1
    print(f"\n   total types across {page} page(s): {total}")
    hits = [t for t in seen if any(k in str(t.get("name", "")).lower()
            for k in ("injur", "sideline", "suspend", "knock", "strain", "fitness"))]
    print(f"   injury-related types: {len(hits)}")
    for t in hits[:60]:
        print(f"      [{t.get('id')}] {t.get('name')}  group={t.get('group')}")


# --------------------------------------------------------------------------- #
# C. Is gating league-level or entity-level?
# --------------------------------------------------------------------------- #
def probe_gating(session, token):
    section("C. GATING LEVEL — can we reach entities from out-of-plan leagues?")
    print("   If a Premier League team/player IS reachable, the plan wall is")
    print("   league-scoped only and coverage may be wider than it looks.\n")

    for name in ("Liverpool", "Real Madrid", "Bayern"):
        status, body = get(session, token, f"{FOOTBALL}/teams/search/{requests.utils.quote(name)}")
        data = (body or {}).get("data", []) or []
        print(f"   teams/search/{name:12} -> HTTP {status}, {len(data)} results"
              + (f"  first: {data[0].get('name')} (id {data[0].get('id')})" if data else ""))
        if data:
            tid = data[0].get("id")
            st2, b2 = get(session, token, f"{FOOTBALL}/teams/{tid}", {"include": "sidelined"})
            recs = ((b2 or {}).get("data") or {}).get("sidelined") or []
            print(f"      -> teams/{tid}?include=sidelined  HTTP {st2}, {len(recs)} records")

    for name in ("Salah", "Haaland"):
        status, body = get(session, token, f"{FOOTBALL}/players/search/{requests.utils.quote(name)}")
        data = (body or {}).get("data", []) or []
        print(f"   players/search/{name:10} -> HTTP {status}, {len(data)} results"
              + (f"  first: {data[0].get('display_name') or data[0].get('name')} "
                 f"(id {data[0].get('id')})" if data else ""))
        if data:
            pid = data[0].get("id")
            st2, b2 = get(session, token, f"{FOOTBALL}/players/{pid}", {"include": "sidelined"})
            recs = ((b2 or {}).get("data") or {}).get("sidelined") or []
            print(f"      -> players/{pid}?include=sidelined  HTTP {st2}, {len(recs)} records")


def main():
    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-deep.{ts}.log")
    print(f"logging responses -> {_state['log']}")

    s = requests.Session()
    probe_backfill(s, token)
    probe_types_properly(s, token)
    probe_gating(s, token)

    section("DONE")
    print("A tells you if history is obtainable at all.")
    print("B tells you if the records are actually rich (or if we mis-read them).")
    print("C tells you if the plan wall is narrower than it appeared.")
    print(f"\nFull responses logged to {_state['log']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
