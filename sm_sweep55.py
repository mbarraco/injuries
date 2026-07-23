#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Sportmonks 55-league sweep — for use ONLY once the Pro trial is active and
all 55 UEFA leagues have been selected in MySportmonks.

Replaces the marketing-page coverage proxy (data/sportmonks_coverage_uefa55.json)
with REAL measured injury data, mirroring exactly what probe.py --mode counts
did for API-Football: per league, per time window, how many `sidelined` records
actually exist.

Uses the nested include proven in sm_deep.py to resolve full records, not bare
pivots:  include=sidelined.sideline;sidelined.player;sidelined.type

Windows span 2015 -> 2026 (same as the earlier Denmark/Scotland probe) so this
answers BREADTH (does this league have any injury data) and DEPTH (how far
back) in one run, for all 55 leagues at once.

Cost: 55 leagues x 6 windows = 330 Fixture-entity calls. Pro plan allows 3000
Fixture calls/hour, so this comfortably fits in a single run.

Usage:
    python sm_sweep55.py
    python sm_sweep55.py --windows 3   # fewer windows, faster, less depth info
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
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
COVERAGE_FILE = os.path.join(os.path.dirname(__file__), "data",
                             "sportmonks_coverage_uefa55.json")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "data",
                            "sportmonks_measured_uefa55.json")

# Same windows used to establish Denmark/Scotland history depth — keeps this
# run directly comparable to that earlier result.
ALL_WINDOWS = [
    ("2015-03-01", "2015-04-01"),
    ("2018-03-01", "2018-04-01"),
    ("2020-02-01", "2020-03-01"),
    ("2022-03-01", "2022-04-01"),
    ("2024-03-01", "2024-04-01"),
    ("2026-03-01", "2026-04-01"),
]

MIN_INTERVAL = 1.1  # 330 calls * 1.1s ~= 6 min; comfortably under 3000/hr
_state = {"last": 0.0, "log": None}


def log_response(url, params, resp, elapsed):
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
            "url": url, "params": safe, "status": resp.status_code,
            "elapsed_s": round(elapsed, 3), "body": body,
        }, ensure_ascii=False) + "\n")


def get(session, token, url, params=None, max_retries=4):
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
        retry_after = r.headers.get("Retry-After")
        wait = int(retry_after) if (retry_after or "").isdigit() else min(60, 10 * (2 ** attempt))
        print(f"    429; waiting {wait}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)
    return 429, None


def get_all_fixtures(session, token, url, params, max_pages=5):
    """Follow pagination so a busy league/window can't silently truncate.

    Sportmonks' default page size is small (observed 50 elsewhere); a top
    league can have 30-50+ fixtures in a one-month window, so a single
    unpaginated call risks under-counting exactly the leagues that matter
    most. per_page=100 plus explicit has_more handling makes this exhaustive.
    """
    all_fixtures = []
    page = 1
    last_status = 200
    first_body = None
    while page <= max_pages:
        p = dict(params)
        p["per_page"] = 100
        p["page"] = page
        status, body = get(session, token, url, p)
        last_status = status
        if page == 1:
            first_body = body
        if status != 200:
            return last_status, all_fixtures, False, first_body
        batch = (body or {}).get("data", []) or []
        all_fixtures.extend(batch)
        pag = (body or {}).get("pagination") or {}
        if not batch or not pag.get("has_more"):
            return status, all_fixtures, False, first_body
        page += 1
    return last_status, all_fixtures, True, first_body  # hit max_pages — truncated


def report_quota(body):
    rl = (body or {}).get("rate_limit") or {}
    if rl:
        print(f"    quota: {rl.get('remaining')} left this hour "
              f"(entity={rl.get('requested_entity')}, resets in {rl.get('resets_in_seconds')}s)")


def section(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Sportmonks 55-league sweep (Pro trial)")
    ap.add_argument("--windows", type=int, default=len(ALL_WINDOWS),
                    help=f"how many windows to test, oldest-first is dropped "
                         f"first (default {len(ALL_WINDOWS)} = full 2015-2026 span)")
    args = ap.parse_args()
    windows = ALL_WINDOWS[-args.windows:] if args.windows < len(ALL_WINDOWS) else ALL_WINDOWS

    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1
    if not os.path.exists(COVERAGE_FILE):
        print(f"! {COVERAGE_FILE} missing")
        return 1

    with open(COVERAGE_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    leagues = doc.get("leagues", [])

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-sweep55.{ts}.log")
    print(f"logging responses -> {_state['log']}")
    print(f"probing {len(leagues)} leagues x {len(windows)} windows = "
          f"{len(leagues) * len(windows)} Fixture calls (~"
          f"{len(leagues) * len(windows) * MIN_INTERVAL / 60:.1f} min)")

    section("SWEEP — real sidelined counts, all 55 leagues, all windows")
    print("Counting ALL `sidelined` pivot entries per fixture (matches the")
    print("method validated in sm_deep.py, which pulled a real closed 2014")
    print("injury record). Resolution rate of the nested `.sideline` detail")
    print("is reported separately — a low rate means records exist but full")
    print("detail doesn't always expand, not that the records are absent.\n")
    session = requests.Session()
    results = []
    first_quota_shown = False
    for i, lg in enumerate(leagues, 1):
        lid, country, lname = lg["id"], lg["country"], lg["league"]
        row = {"country": country, "league": lname, "id": lid, "windows": {}}
        counts, resolved_counts = [], []
        for d1, d2 in windows:
            # NOTE: Sportmonks returns HTTP 200 + empty data for out-of-plan
            # leagues (proven in sm_deep.py section C), not 403 — so this
            # cannot actually distinguish "not in plan" from "genuinely zero".
            # We rely on sm_check_plan.py having verified plan access upfront.
            status, fixtures, truncated, first_body = get_all_fixtures(
                session, token, f"{FOOTBALL}/fixtures/between/{d1}/{d2}",
                {"filters": f"fixtureLeagues:{lid}", "include": "sidelined.sideline"})
            if not first_quota_shown and status == 200:
                report_quota(first_body)
                first_quota_shown = True
            if status == 403:
                row["windows"][d1[:4]] = "not_in_plan"
                continue
            if status != 200:
                row["windows"][d1[:4]] = f"http_{status}"
                continue
            if truncated:
                print(f"    ! {country} {d1}: hit page cap, counts may be truncated")
            entries = [s for f in fixtures for s in (f.get("sidelined") or [])]
            n = len(entries)
            n_resolved = sum(1 for s in entries if s.get("sideline"))
            row["windows"][d1[:4]] = n
            counts.append(n)
            resolved_counts.append(n_resolved)
        total = sum(counts)
        total_resolved = sum(resolved_counts)
        row["total"] = total
        row["total_resolved"] = total_resolved
        row["years_with_data"] = sum(1 for c in counts if c > 0)
        results.append(row)
        bar = " ".join(f"{y}:{v}" for y, v in row["windows"].items())
        pct = f"{100 * total_resolved / total:.0f}%" if total else "n/a"
        print(f"  [{i:2}/{len(leagues)}] {country:24} {lname:22} {bar}   "
              f"total={total} (resolved={total_resolved}, {pct})")

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "windows": windows, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results saved to {RESULTS_FILE}")

    section("SUMMARY — tiered, same method as the API-Football comparison")
    ranked = sorted(results, key=lambda r: -r["total"])
    rich = [r for r in ranked if r["years_with_data"] >= 4 and r["total"] >= 200]
    moderate = [r for r in ranked if r not in rich and r["total"] >= 50]
    thin = [r for r in ranked if r not in rich and r not in moderate and r["total"] > 0]
    dark = [r for r in ranked if r["total"] == 0]

    def line(rs):
        return ", ".join(f"{r['country']} {r['total']}" for r in rs) or "none"

    print(f"  RICH   (data in {'>=4'} of {len(windows)} windows, total>=200): {len(rich)}")
    print(f"     {line(rich)}")
    print(f"  MODERATE (total>=50): {len(moderate)}")
    print(f"     {line(moderate)}")
    print(f"  THIN (total>0):        {len(thin)}")
    print(f"     {line(thin)}")
    print(f"  DARK (total==0):       {len(dark)}")
    print(f"     {line(dark)}")

    print("\nCompare directly against the API-Football verified result:")
    print("  API-Football: 11 rich (2023-2025), ~7 usable-2025-only, ~25 thin, 12 dark")
    print(f"  Sportmonks:   {len(rich)} rich, {len(moderate)} moderate, "
          f"{len(thin)} thin, {len(dark)} dark  (measured 2015-2026)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
