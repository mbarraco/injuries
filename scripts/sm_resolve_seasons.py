#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Resolve season_id references into real season names + boundaries.

Every cached fixture in data/raw/sportmonks/fixtures/*.json carries a
season_id, but we've never fetched what that id actually means for any
league except the two free ones explored early on (Denmark/Scotland).

This also fixes a real accuracy gap: the sweep's tier analysis approximated
"season" as a rolling 12 calendar months, because we didn't know each
league's real season boundaries (Aug-May for most of Europe, Mar-Nov
calendar-year for several Nordic/Baltic leagues). Fetching each league's
actual season list gives real boundaries for any future ingestion to use
instead of that approximation.

Cost: 53 calls total (one per league, via /leagues/{id}?include=seasons —
proven to work in sm_explore.py). Uses the League entity's own hourly quota
bucket, separate from Player/Team/Fixture, so it doesn't compete with
sm_resolve_entities.py if that's still running.

Usage:
    python sm_resolve_seasons.py
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

FOOTBALL = "https://api.sportmonks.com/v3/football"
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
COVERAGE_FILE = os.path.join(os.path.dirname(__file__), "data",
                             "sportmonks_coverage_uefa55.json")
RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw",
                       "sportmonks", "seasons")
SEASONS_FILE = os.path.join(os.path.dirname(__file__), "data",
                            "sportmonks_seasons.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "coverage.db")
DEFAULT_CONCURRENCY = 3

_state = {"log": None}
_log_lock = threading.Lock()


def log_response(url, params, resp, elapsed):
    if not _state.get("log"):
        return
    safe = {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:2000]}
    record = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url, "params": safe, "status": resp.status_code,
        "elapsed_s": round(elapsed, 3), "body": body,
    }, ensure_ascii=False) + "\n"
    with _log_lock:
        with open(_state["log"], "a", encoding="utf-8") as f:
            f.write(record)


def get(session, token, url, params=None, max_retries=4):
    p = {"api_token": token}
    p.update(params or {})
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        r = session.get(url, params=p, timeout=30)
        log_response(url, p, r, time.monotonic() - t0)
        if r.status_code != 429:
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        retry_after = r.headers.get("Retry-After")
        wait = int(retry_after) if (retry_after or "").isdigit() else min(60, 10 * (2 ** attempt))
        print(f"\n    429; waiting {wait}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(wait)
    return 429, None


def section(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def fetch_league_seasons(session, token, league_id, refresh=False):
    """Cache the FULL raw response (not just id/name) — season objects may
    carry date-like fields under names we haven't confirmed yet; caching
    everything means we don't need to re-fetch to find out later."""
    path = os.path.join(RAW_DIR, f"{league_id}.json")
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return 200, json.load(f), True
    status, body = get(session, token, f"{FOOTBALL}/leagues/{league_id}",
                       {"include": "seasons"})
    if status != 200:
        return status, None, False
    data = (body or {}).get("data") or {}
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return status, data, False


DATE_FIELD_CANDIDATES = ("starting_at", "ending_at", "start_date", "end_date",
                         "started_at", "finished_at")


def extract_dates(season):
    """Pull whatever date-like fields are actually present — field naming
    for season boundaries was never confirmed, so check several candidates
    rather than assume one."""
    found = {}
    for k in DATE_FIELD_CANDIDATES:
        if season.get(k):
            found[k] = season[k]
    return found


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sportmonks_season (
            id          TEXT PRIMARY KEY,
            league_id   TEXT,
            country     TEXT,
            league_name TEXT,
            name        TEXT,
            is_current  INTEGER,
            dates_json  TEXT
        );
        """
    )
    conn.commit()
    return conn


def save_seasons(conn, rows):
    conn.executemany(
        "INSERT OR REPLACE INTO sportmonks_season VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Resolve Sportmonks season ids to names/boundaries")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--refresh", action="store_true",
                    help="ignore cache, re-fetch every league's season list")
    args = ap.parse_args()

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
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-seasons.{ts}.log")
    print(f"logging responses -> {_state['log']}")

    section(f"SEASONS — resolving all {len(leagues)} leagues "
            f"(concurrency={args.concurrency})")
    session = requests.Session()
    league_results = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(fetch_league_seasons, session, token, lg["id"], args.refresh): lg
            for lg in leagues
        }
        done = 0
        for fut in as_completed(futures):
            lg = futures[fut]
            status, data, from_cache = fut.result()
            done += 1
            tag = " (cache)" if from_cache else ""
            if status != 200 or not data:
                print(f"  [{done:2}/{len(leagues)}] {lg['country']:24} -> HTTP {status}{tag}")
                continue
            n_seasons = len(data.get("seasons") or [])
            print(f"  [{done:2}/{len(leagues)}] {lg['country']:24} -> "
                  f"{n_seasons} seasons{tag}")
            league_results[lg["id"]] = (lg, data)

    section("CONSOLIDATING — flattening into one season_id -> info lookup")
    season_lookup, db_rows = {}, []
    for league_id, (lg, data) in league_results.items():
        for season in (data.get("seasons") or []):
            sid = season.get("id")
            if not sid:
                continue
            dates = extract_dates(season)
            entry = {
                "league_id": league_id, "country": lg["country"],
                "league_name": lg["league"], "name": season.get("name"),
                "is_current": bool(season.get("is_current")), "dates": dates,
            }
            season_lookup[str(sid)] = entry
            db_rows.append((str(sid), str(league_id), lg["country"], lg["league"],
                           season.get("name"), int(bool(season.get("is_current"))),
                           json.dumps(dates, ensure_ascii=False)))

    with open(SEASONS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seasons": season_lookup,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n{len(season_lookup)} total seasons across {len(league_results)} "
          f"leagues -> {SEASONS_FILE}")

    conn = init_db()
    save_seasons(conn, db_rows)
    conn.close()
    print(f"Written to sportmonks_season table in {DB_PATH}")

    if not any(e["dates"] for e in season_lookup.values()):
        print("\nNOTE: no date fields were found on any season object under the "
              "candidate names tried ({}). Season NAMES resolved fine; if real "
              "date boundaries are needed later, inspect a raw file under "
              f"{RAW_DIR} to find the correct field name and extend "
              "DATE_FIELD_CANDIDATES.".format(", ".join(DATE_FIELD_CANDIDATES)))

    missing = len(leagues) - len(league_results)
    if missing:
        print(f"\n! {missing} league(s) failed to resolve — re-run to retry "
              f"just those (everything else is cached).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
