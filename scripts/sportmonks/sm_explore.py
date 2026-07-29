#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Sportmonks self-discovery probe.

We only have Denmark (#271) and Scotland (#501) in the free plan, but those two
leagues can answer the questions that decide whether Sportmonks is worth paying
for — WITHOUT sending anyone an email:

  1. How far back does `sidelined` (injury) history actually go?
  2. How rich is a single injury record (fields, type taxonomy)?
  3. What exactly does the plan wall look like for out-of-plan leagues?
  4. Which include names / endpoints actually work (docs are vague)?

Every response is logged to logs/sportmonks-explore.<ts>.log (token redacted).

Usage:
    python sm_explore.py
    python sm_explore.py --teams 6      # probe fewer teams (fewer calls)
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
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")

# Known in-plan leagues (from the earlier probe run).
IN_PLAN = {271: "Superliga (Denmark)", 501: "Premiership (Scotland)"}
# Known out-of-plan league ids (Sportmonks' own coverage page ids) — used to
# characterise the plan wall: does it 403, or silently return nothing?
OUT_OF_PLAN = {8: "Premier League (ENG)", 564: "La Liga (ESP)",
               82: "Bundesliga (GER)", 384: "Serie A (ITA)"}

MIN_INTERVAL = 0.8
_state = {"last": 0.0, "log": None}


# --------------------------------------------------------------------------- #
# HTTP + logging
# --------------------------------------------------------------------------- #
def log_response(url, params, resp, elapsed):
    if not _state.get("log"):
        return
    safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:4000]}
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url, "params": safe, "status": resp.status_code,
        "elapsed_s": round(elapsed, 3), "body": body,
    }
    with open(_state["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def get(session, token, url, params=None, max_retries=3):
    """Paced GET with 429 backoff. Returns (status, json_or_None)."""
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


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #
COVERAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                             "reference", "sportmonks", "coverage_uefa55.json")


def report_published_coverage():
    """Sportmonks' own published per-league coverage for the 55 UEFA leagues.

    Their API cannot answer this (no coverage flag, /leagues is plan-filtered),
    so this comes from their public coverage page. Injuries are NOT a published
    feature, so player-level coverage is used as an upper bound.
    """
    section("0. PUBLISHED COVERAGE — the 55 UEFA leagues (proxy, from their site)")
    if not os.path.exists(COVERAGE_FILE):
        print(f"   ! {COVERAGE_FILE} missing")
        return []
    with open(COVERAGE_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    leagues = doc.get("leagues", [])
    both = [l for l in leagues if l["advanced_player_stats"] and l["standard_player_stats"]]
    std = [l for l in leagues if l["standard_player_stats"] and not l["advanced_player_stats"]]
    none = [l for l in leagues if not l["standard_player_stats"] and not l["advanced_player_stats"]]
    odd = [l for l in leagues if l["advanced_player_stats"] and not l["standard_player_stats"]]

    print(f"   {len(leagues)} UEFA top-tier leagues on their coverage page")
    print(f"   Advanced + Standard player stats : {len(both):2}  (strongest injury candidates)")
    print(f"   Standard player stats only       : {len(std):2}")
    print(f"   Advanced only (page quirk)       : {len(odd):2}")
    print(f"   No player-level data             : {len(none):2}  (cannot carry injuries)")
    ceiling = len(both) + len(std) + len(odd)
    print(f"\n   UPPER BOUND on injury coverage: {ceiling}/{len(leagues)} leagues")
    print(f"   (API-Football's VERIFIED injury coverage: 43/55, at ~1/13th the price)")

    print("\n   Advanced + Standard:")
    for l in both:
        tag = "  <- in your free plan" if l.get("in_free_plan") else ""
        print(f"      {l['country']:24} {l['league']} #{l['id']}{tag}")
    print("\n   Standard only:")
    print("      " + ", ".join(l["country"] for l in std))
    print("\n   No player-level data:")
    print("      " + ", ".join(l["country"] for l in none + odd))
    for k, v in (doc.get("_missing") or {}).items():
        print(f"\n   NOT LISTED: {k} — {v}")
    return leagues


def probe_plan_wall(session, token):
    """What does the plan actually expose, and how does it refuse the rest?"""
    section("1. PLAN WALL — what we can and cannot see")
    status, body = get(session, token, f"{FOOTBALL}/leagues",
                       {"include": "country", "per_page": "100"})
    data = (body or {}).get("data", []) if status == 200 else []
    print(f"/leagues -> HTTP {status}, {len(data)} leagues in plan:")
    for it in data:
        country = (it.get("country") or {}).get("name", "?")
        print(f"   - [{it.get('id')}] {it.get('name')} ({country})")

    print("\nOut-of-plan league lookups (does metadata leak, or hard 403?):")
    for lid, name in OUT_OF_PLAN.items():
        status, body = get(session, token, f"{FOOTBALL}/leagues/{lid}")
        msg = (body or {}).get("message", "")
        print(f"   - [{lid}] {name:22} -> HTTP {status} {str(msg)[:80]}")


def probe_seasons(session, token):
    """How many seasons of data exist per in-plan league, and how far back?"""
    section("2. SEASON DEPTH — how far back does each league go at all?")
    out = {}
    for lid, name in IN_PLAN.items():
        status, body = get(session, token, f"{FOOTBALL}/leagues/{lid}",
                           {"include": "seasons"})
        if status != 200:
            print(f"   {name}: HTTP {status} — cannot read seasons")
            continue
        seasons = ((body or {}).get("data") or {}).get("seasons", []) or []
        seasons_sorted = sorted(seasons, key=lambda s: str(s.get("name", "")))
        names = [s.get("name") for s in seasons_sorted]
        out[lid] = seasons_sorted
        print(f"   {name}: {len(seasons)} seasons")
        if names:
            print(f"      earliest: {names[0]}   latest: {names[-1]}")
    return out


def probe_direct_sidelined(session, token):
    """Is there a top-level sidelined endpoint, or is it include-only?"""
    section("3. IS THERE A DIRECT `sidelined` ENDPOINT?")
    for path in ("/sidelined", "/sidelined/latest"):
        status, body = get(session, token, f"{FOOTBALL}{path}", {"per_page": "5"})
        n = len((body or {}).get("data", []) or []) if status == 200 else 0
        msg = (body or {}).get("message", "") if status != 200 else ""
        print(f"   GET {path:20} -> HTTP {status} "
              f"{'records: ' + str(n) if status == 200 else str(msg)[:90]}")


def probe_sidelined_history(session, token, seasons_by_league, max_teams):
    """The key question: how deep does injury history actually go?

    Strategy: take the most recent season of each in-plan league, list its
    teams, then pull each team's sidelined history and look at the date range.
    """
    section("4. INJURY HISTORY DEPTH + RECORD RICHNESS")
    all_records = []
    sample = None
    working_include = None

    for lid, name in IN_PLAN.items():
        seasons = seasons_by_league.get(lid) or []
        if not seasons:
            print(f"   {name}: no seasons known, skipping")
            continue
        latest = seasons[-1]
        sid = latest.get("id")
        print(f"\n   {name} — using season '{latest.get('name')}' (id {sid})")

        status, body = get(session, token, f"{FOOTBALL}/teams/seasons/{sid}")
        if status != 200:
            print(f"      teams/seasons/{sid} -> HTTP {status}; skipping league")
            continue
        teams = (body or {}).get("data", []) or []
        print(f"      {len(teams)} teams; probing up to {max_teams}")

        for team in teams[:max_teams]:
            tid, tname = team.get("id"), team.get("name")
            # Docs are vague on the exact include name — try both.
            for inc in ("sidelinedHistory", "sidelined"):
                status, body = get(session, token, f"{FOOTBALL}/teams/{tid}",
                                   {"include": inc})
                if status != 200:
                    continue
                data = (body or {}).get("data") or {}
                recs = data.get(inc) or data.get("sidelined") or []
                if recs:
                    working_include = inc
                    all_records.extend(recs)
                    if sample is None:
                        sample = recs[0]
                    print(f"      {tname:28} {len(recs):4} records (include={inc})")
                    break
            else:
                print(f"      {tname:28} no sidelined data")

    print(f"\n   TOTAL sidelined records collected: {len(all_records)}")
    if working_include:
        print(f"   Working include name: `{working_include}`")

    # History depth: look at whatever date-ish fields exist.
    dates = []
    for r in all_records:
        for key in ("start_date", "starting_at", "start", "date"):
            v = r.get(key)
            if isinstance(v, str) and len(v) >= 4:
                dates.append(v[:10])
                break
    if dates:
        dates.sort()
        print(f"   Date range of records: {dates[0]}  ->  {dates[-1]}")
        years = sorted({d[:4] for d in dates})
        print(f"   Distinct years present: {', '.join(years)}")
    else:
        print("   ! No recognisable date field found — inspect the sample below.")

    if sample:
        print("\n   FULL SAMPLE RECORD (all fields — this is the richness test):")
        print("   " + json.dumps(sample, indent=2, ensure_ascii=False).replace("\n", "\n   "))
    return all_records


def probe_player_history(session, token, records, max_players=5):
    """Decisive test: is there a real injury ARCHIVE, or only current absences?

    The team-level `sidelined` include returns only open/active absences. If a
    player endpoint returns many past, completed records, an archive exists and
    Sportmonks is worth reconsidering. If it returns the same 1-2 open records,
    there is no queryable history and the archive would have to be rebuilt by
    crawling every fixture of every season.
    """
    section("4b. IS THERE A REAL ARCHIVE? (player-level history)")
    player_ids = []
    for r in records:
        pid = r.get("player_id")
        if pid and pid not in player_ids:
            player_ids.append(pid)
    if not player_ids:
        print("   no player_ids collected; skipping")
        return
    print(f"   testing {min(len(player_ids), max_players)} players\n")
    for pid in player_ids[:max_players]:
        best = None
        for inc in ("sidelined", "sidelinedHistory"):
            status, body = get(session, token, f"{FOOTBALL}/players/{pid}",
                               {"include": inc})
            if status != 200:
                print(f"   player {pid} include={inc:18} HTTP {status}")
                continue
            data = (body or {}).get("data") or {}
            recs = data.get(inc) or data.get("sidelined") or []
            completed = sum(1 for r in recs if r.get("completed") is True)
            dates = sorted(str(r.get("start_date") or "")[:10] for r in recs if r.get("start_date"))
            print(f"   player {pid} include={inc:18} {len(recs):3} records "
                  f"({completed} completed)"
                  + (f"  {dates[0]} -> {dates[-1]}" if dates else ""))
            if recs and (best is None or len(recs) > best):
                best = len(recs)
    print("\n   READ THIS AS: many COMPLETED records spanning years = real archive.")
    print("   Only open/uncompleted records = current snapshot, no history.")


def probe_types(session, token):
    """Injury type taxonomy — how granular are the injury categories?"""
    section("5. INJURY TYPE TAXONOMY")
    status, body = get(session, token, f"{CORE}/types", {"per_page": "500"})
    if status != 200:
        print(f"   /core/types -> HTTP {status}")
        return
    data = (body or {}).get("data", []) or []
    print(f"   {len(data)} types total")
    hits = [t for t in data
            if any(k in str(t.get("name", "")).lower() or k in str(t.get("group", "")).lower()
                   for k in ("injur", "sideline", "suspend", "fitness"))]
    print(f"   injury/suspension-related types: {len(hits)}")
    for t in hits[:40]:
        print(f"      [{t.get('id')}] {t.get('name')}  (group={t.get('group')})")


# --------------------------------------------------------------------------- #
def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Sportmonks self-discovery probe")
    ap.add_argument("--teams", type=int, default=8,
                    help="max teams per league to probe (default 8)")
    args = ap.parse_args()

    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-explore.{ts}.log")
    print(f"logging responses -> {_state['log']}")

    s = requests.Session()
    report_published_coverage()
    probe_plan_wall(s, token)
    seasons = probe_seasons(s, token)
    probe_direct_sidelined(s, token)
    records = probe_sidelined_history(s, token, seasons, args.teams)
    probe_player_history(s, token, records)
    probe_types(s, token)

    section("6. VERDICT INPUTS")
    print("   Coverage (breadth): capped by the published proxy in section 0 —")
    print("     Sportmonks cannot beat API-Football's verified 43/55 on breadth.")
    if records:
        print(f"   History (depth): {len(records)} sidelined records observed for the")
        print("     in-plan leagues. Compare the date range above against")
        print("     API-Football's ~2 seasons (2023+, and only for 11 UEFA leagues).")
        print("     Deep history here is the ONLY thing that could justify €249/mo.")
    else:
        print("   History (depth): no sidelined records retrieved — if this is a")
        print("     probe bug rather than missing data, check the log before concluding.")
    section("DONE")
    print(f"Full responses logged to {_state['log']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
