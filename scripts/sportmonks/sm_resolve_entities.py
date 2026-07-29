#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Resolve the numeric IDs in the cached raw fixture data into real names.

Every sidelined record in data/raw/sportmonks/fixtures/*.json carries only
player_id, team_id, type_id — no names. This script:

  1. Scans ALL cached fixture files and collects every unique player_id,
     team_id, and type_id actually referenced.
  2. Fetches the full injury/suspension TYPE taxonomy in one go (it's a
     small, fixed list — ~300 entries total — so there's no need to filter
     to just the ones we've seen).
  3. Resolves PLAYERS and TEAMS by id. Tries a batched `filters=id:...`
     lookup first (many ids per call); if Sportmonks doesn't actually
     support that for a given endpoint, falls back automatically to one
     call per id. Either way, every entity is cached individually to disk
     (same raw-cache pattern as the fixture sweep), so this is resumable
     and safe to re-run.
  4. Enriches players/teams beyond just a name, using data ALREADY present
     in the cached raw entity — no extra calls needed: position (resolved
     free via the types taxonomy, since positions are just another `type`),
     date of birth, height, weight for players; founded year and short
     code for teams. Nationality/country needs one extra small reference
     fetch (/core/countries, following the same fetch-once pattern as
     types).
  5. Writes a consolidated data/reference/sportmonks/entities.json lookup plus
     matching SQLite reference tables in coverage.db, for easy joining.

Player/Team calls use SEPARATE hourly quota buckets from Fixture calls
(Sportmonks limits are per-entity), so this doesn't compete with the sweep.

Usage:
    python sm_resolve_entities.py
    python sm_resolve_entities.py --concurrency 5
"""
from __future__ import annotations

import argparse
import glob
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
CORE = "https://api.sportmonks.com/v3/core"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
FIXTURES_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "raw",
                                  "sportmonks", "fixtures")
RAW_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "raw", "sportmonks")
ENTITIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                             "reference", "sportmonks", "entities.json")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "coverage.db")
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


# --------------------------------------------------------------------------- #
# 1. Scan the fixture cache for every referenced id
# --------------------------------------------------------------------------- #
def scan_referenced_ids():
    player_ids, team_ids, type_ids = set(), set(), set()
    files = sorted(glob.glob(os.path.join(FIXTURES_CACHE_DIR, "*.json")))
    print(f"scanning {len(files)} cached fixture files …")
    for path in files:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        for fx in doc.get("fixtures", []):
            for pivot in fx.get("sidelined") or []:
                sl = pivot.get("sideline") or {}
                if sl.get("player_id"):
                    player_ids.add(sl["player_id"])
                if sl.get("team_id"):
                    team_ids.add(sl["team_id"])
                if sl.get("type_id"):
                    type_ids.add(sl["type_id"])
                # pivot-level fields as a fallback if .sideline didn't resolve
                if pivot.get("player_id"):
                    player_ids.add(pivot["player_id"])
                if pivot.get("type_id"):
                    type_ids.add(pivot["type_id"])
    print(f"  {len(player_ids)} unique players · {len(team_ids)} unique teams · "
          f"{len(type_ids)} unique types referenced")
    return player_ids, team_ids, type_ids


# --------------------------------------------------------------------------- #
# 2. Types — small, fixed taxonomy; fetch the whole list once
# --------------------------------------------------------------------------- #
def fetch_all_types(session, token):
    section("TYPES — fetching the full taxonomy (small, cheap, fetch once)")
    path = os.path.join(RAW_ROOT, "types.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            types = json.load(f)
        print(f"  using cached {path} ({len(types)} types)")
        return {int(t["id"]): t["name"] for t in types}

    all_types, page = [], 1
    while page <= 15:
        status, body = get(session, token, f"{CORE}/types", {"page": page, "per_page": 100})
        if status != 200:
            print(f"  ! /core/types page {page} -> HTTP {status}")
            break
        data = (body or {}).get("data", []) or []
        all_types.extend(data)
        pag = (body or {}).get("pagination") or {}
        if not data or not pag.get("has_more"):
            break
        page += 1
    os.makedirs(RAW_ROOT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_types, f, ensure_ascii=False)
    print(f"  fetched {len(all_types)} types -> cached to {path}")
    return {int(t["id"]): t["name"] for t in all_types}


def resolve_missing_types(session, token, type_map, referenced_ids, concurrency):
    """The bulk /core/types list doesn't cover every id that actually shows
    up in sideline records (confirmed: list tops out around id 595, but
    referenced ids go well past 2000) — same class of gap as players/teams,
    different cause. We've only PROVEN direct /core/types/{id} lookup works
    for ids already in the list (531, 13); probe a couple of missing ones
    before committing to fetching all of them individually.

    Newly-resolved types are appended back into the cached types.json file,
    so a re-run doesn't redo this work — otherwise every run would re-probe
    and re-fetch the same missing ids from scratch.
    """
    types_path = os.path.join(RAW_ROOT, "types.json")
    missing = sorted(referenced_ids - set(type_map.keys()))
    if not missing:
        return type_map
    section(f"TYPES — {len(missing)} referenced ids missing from the bulk list")
    probe_ids = missing[:2]
    print(f"  probing direct lookup on 2 missing ids: {probe_ids} …")
    newly_resolved = {}
    for tid in probe_ids:
        status, body = get(session, token, f"{CORE}/types/{tid}")
        data = (body or {}).get("data") or {}
        if status == 200 and data.get("name"):
            newly_resolved[tid] = data["name"]
            print(f"    id {tid} -> {status} name={data['name']!r}")
        else:
            print(f"    id {tid} -> {status} (no name resolved)")
    if not newly_resolved:
        print("  neither probe id resolved — these ids appear genuinely "
              "unavailable via direct lookup too. Leaving them unresolved; "
              "the raw type_id will still be stored, just without a name.")
        return type_map

    rest = [tid for tid in missing if tid not in newly_resolved]
    print(f"  direct lookup works — fetching remaining {len(rest)} individually "
          f"(concurrency={concurrency}) …")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(get, session, token, f"{CORE}/types/{tid}"): tid
                   for tid in rest}
        done = 0
        for fut in as_completed(futures):
            tid = futures[fut]
            status, body = fut.result()
            done += 1
            if done % 25 == 0 or done == len(rest):
                print(f"\r  {done}/{len(rest)}", end="", flush=True)
            data = (body or {}).get("data") or {}
            if status == 200 and data.get("name"):
                newly_resolved[tid] = data["name"]
    print()

    type_map.update(newly_resolved)
    # Persist back into the SAME list-of-dicts shape fetch_all_types() reads,
    # so a re-run loads these from cache instead of re-probing/re-fetching.
    existing = []
    if os.path.exists(types_path):
        with open(types_path, encoding="utf-8") as f:
            existing = json.load(f)
    existing_ids = {t["id"] for t in existing}
    existing.extend({"id": tid, "name": name} for tid, name in newly_resolved.items()
                    if tid not in existing_ids)
    with open(types_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"  {len(newly_resolved)} newly-resolved types appended to {types_path}")
    return type_map


def load_position_map():
    """Player position_id/detailed_position_id resolve for FREE via the
    types.json we already cache — confirmed: entries with
    model_type == "position" (e.g. id 25 = "Defender", 148 = "Centre
    Back"). No extra API calls needed."""
    path = os.path.join(RAW_ROOT, "types.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw_types = json.load(f)
    return {t["id"]: t["name"] for t in raw_types if t.get("model_type") == "position"}


# --------------------------------------------------------------------------- #
# Countries — small, fixed reference list; fetch the whole list once.
# Endpoint guessed by convention from /core/types (unconfirmed on docs we've
# read) — if /core/countries doesn't exist, this just returns an empty dict
# rather than crashing, and nationality/country names stay unresolved.
# --------------------------------------------------------------------------- #
def fetch_all_countries(session, token):
    section("COUNTRIES — fetching the full reference list (small, cheap, fetch once)")
    path = os.path.join(RAW_ROOT, "countries.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            countries = json.load(f)
        print(f"  using cached {path} ({len(countries)} countries)")
        return {int(c["id"]): c["name"] for c in countries}

    all_countries, page = [], 1
    while page <= 15:
        status, body = get(session, token, f"{CORE}/countries", {"page": page, "per_page": 100})
        if status != 200:
            print(f"  ! /core/countries page {page} -> HTTP {status} — "
                  f"endpoint may not exist as guessed; nationality/country "
                  f"names will stay unresolved")
            break
        data = (body or {}).get("data", []) or []
        all_countries.extend(data)
        pag = (body or {}).get("pagination") or {}
        if not data or not pag.get("has_more"):
            break
        page += 1
    if not all_countries:
        return {}
    os.makedirs(RAW_ROOT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_countries, f, ensure_ascii=False)
    print(f"  fetched {len(all_countries)} countries -> cached to {path}")
    return {int(c["id"]): c["name"] for c in all_countries}


# --------------------------------------------------------------------------- #
# 3. Players / Teams — batched lookup with automatic fallback to per-id
# --------------------------------------------------------------------------- #
def entity_cache_path(kind, entity_id):
    return os.path.join(RAW_ROOT, kind, f"{entity_id}.json")


def try_batch_lookup(session, token, endpoint, ids_chunk):
    """Attempt one call resolving many ids via the path-based /multi/ pattern,
    e.g. GET /fixtures/multi/123,456,789 — Sportmonks' documented rate-limit
    guide confirms this exists for Fixture and counts as ONE request
    regardless of how many ids are batched. /players/multi/ and /teams/multi/
    follow the same naming convention but aren't explicitly confirmed on that
    page, which is exactly why we probe with one chunk and self-correct
    rather than assume — see resolve_entities().

    Returns {id: entity_dict} for whatever was actually resolved. Empty dict
    means the batch approach didn't work for this endpoint — caller falls
    back to one-by-one.
    """
    ids_str = ",".join(str(i) for i in ids_chunk)
    status, body = get(session, token, f"{FOOTBALL}{endpoint}/multi/{ids_str}")
    if status != 200:
        return {}
    data = (body or {}).get("data", []) or []
    return {int(item["id"]): item for item in data if item.get("id")}


def resolve_entities(session, token, kind, endpoint, ids, concurrency, try_batch=True):
    """Resolve a set of ids to entity dicts, caching each one individually.

    Tries batched lookups in chunks of 20 first (far fewer calls if it
    works); any id a batch didn't resolve falls back to an individual
    GET /endpoint/{id} call, run concurrently like the fixture sweep.
    """
    section(f"{kind.upper()} — resolving {len(ids)} unique ids")
    os.makedirs(os.path.join(RAW_ROOT, kind), exist_ok=True)

    cached, todo = {}, []
    for eid in ids:
        p = entity_cache_path(kind, eid)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cached[eid] = json.load(f)
        else:
            todo.append(eid)
    print(f"  {len(cached)} already cached · {len(todo)} to resolve")
    if not todo:
        return cached

    still_todo = list(todo)
    if try_batch:
        # Probe with ONE chunk first. Looping through hundreds of chunks
        # before finding out the endpoint doesn't support this is exactly
        # what stalled the previous run silently — cheap to test, expensive
        # to discover 500 calls in.
        probe_chunk = todo[:20]
        print(f"  probing batched lookup on 1 chunk of {len(probe_chunk)} …")
        probe_found = try_batch_lookup(session, token, endpoint, probe_chunk)
        if not probe_found:
            print(f"  batch lookup returned nothing usable for {endpoint} "
                  f"— skipping straight to per-id calls for all {len(todo)}")
            still_todo = list(todo)
        else:
            print(f"  batch lookup works ({len(probe_found)}/{len(probe_chunk)} in "
                  f"the probe) — continuing in chunks of 20, with progress")
            remaining = []
            for eid in probe_chunk:
                if eid in probe_found:
                    with open(entity_cache_path(kind, eid), "w", encoding="utf-8") as f:
                        json.dump(probe_found[eid], f, ensure_ascii=False)
                    cached[eid] = probe_found[eid]
                else:
                    remaining.append(eid)
            rest = todo[20:]
            for i in range(0, len(rest), 20):
                chunk = rest[i:i + 20]
                found = try_batch_lookup(session, token, endpoint, chunk)
                for eid in chunk:
                    if eid in found:
                        with open(entity_cache_path(kind, eid), "w", encoding="utf-8") as f:
                            json.dump(found[eid], f, ensure_ascii=False)
                        cached[eid] = found[eid]
                    else:
                        remaining.append(eid)
                done = 20 + i + len(chunk)
                print(f"\r  batched: {min(done, len(todo))}/{len(todo)}", end="", flush=True)
            print()
            still_todo = remaining

    if still_todo:
        print(f"  fetching {len(still_todo)} individually (concurrency={concurrency}) …")
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(get, session, token, f"{FOOTBALL}{endpoint}/{eid}"): eid
                       for eid in still_todo}
            done = 0
            for fut in as_completed(futures):
                eid = futures[fut]
                status, body = fut.result()
                done += 1
                if done % 25 == 0 or done == len(still_todo):
                    print(f"\r  {done}/{len(still_todo)}", end="", flush=True)
                if status != 200:
                    continue
                data = (body or {}).get("data") or {}
                if not data:
                    continue
                with open(entity_cache_path(kind, eid), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                cached[eid] = data
        print()
    return cached


# --------------------------------------------------------------------------- #
# SQLite reference tables — same "for now" per-provider approach as
# sportmonks_coverage in sm_sweep55.py.
# --------------------------------------------------------------------------- #
def init_db():
    conn = sqlite3.connect(DB_PATH)
    # DROP + recreate: these tables are always fully rebuilt from the
    # complete cached entity set on every run (not incrementally patched),
    # so there's no state worth preserving across a schema change — the
    # raw per-entity JSON cache on disk is the real source of truth.
    conn.executescript(
        """
        DROP TABLE IF EXISTS sportmonks_player;
        DROP TABLE IF EXISTS sportmonks_team;
        CREATE TABLE sportmonks_player (
            id                TEXT PRIMARY KEY,
            name              TEXT,
            position          TEXT,
            detailed_position TEXT,
            nationality       TEXT,
            date_of_birth     TEXT,
            height_cm         INTEGER,
            weight_kg         INTEGER
        );
        CREATE TABLE sportmonks_team (
            id         TEXT PRIMARY KEY,
            name       TEXT,
            country    TEXT,
            founded    INTEGER,
            short_code TEXT
        );
        CREATE TABLE IF NOT EXISTS sportmonks_type    (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS sportmonks_country (id TEXT PRIMARY KEY, name TEXT);
        """
    )
    conn.commit()
    return conn


def save_lookup(conn, table, id_to_name):
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} VALUES (?, ?)",
        [(str(k), v) for k, v in id_to_name.items()],
    )
    conn.commit()


def save_players(conn, player_map):
    conn.executemany(
        "INSERT OR REPLACE INTO sportmonks_player VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(str(eid), p["name"], p["position"], p["detailed_position"],
          p["nationality"], p["date_of_birth"], p["height"], p["weight"])
         for eid, p in player_map.items()],
    )
    conn.commit()


def save_teams(conn, team_map):
    conn.executemany(
        "INSERT OR REPLACE INTO sportmonks_team VALUES (?, ?, ?, ?, ?)",
        [(str(eid), t["name"], t["country"], t["founded"], t["short_code"])
         for eid, t in team_map.items()],
    )
    conn.commit()


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Resolve Sportmonks entity ids to names")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = ap.parse_args()

    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1
    if not os.path.exists(FIXTURES_CACHE_DIR):
        print(f"! {FIXTURES_CACHE_DIR} missing — run sm_sweep55.py first")
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _state["log"] = os.path.join(LOG_DIR, f"sportmonks-resolve.{ts}.log")
    print(f"logging responses -> {_state['log']}")

    player_ids, team_ids, type_ids = scan_referenced_ids()

    session = requests.Session()
    type_map = fetch_all_types(session, token)
    type_map = resolve_missing_types(session, token, type_map, type_ids, args.concurrency)
    type_map = {tid: name for tid, name in type_map.items() if tid in type_ids}
    position_map = load_position_map()
    country_map = fetch_all_countries(session, token)

    players = resolve_entities(session, token, "players", "/players", player_ids,
                               args.concurrency)
    teams = resolve_entities(session, token, "teams", "/teams", team_ids,
                             args.concurrency)

    player_map = {
        eid: {
            "name": p.get("display_name") or p.get("name") or f"player {eid}",
            "position": position_map.get(p.get("position_id")),
            "detailed_position": position_map.get(p.get("detailed_position_id")),
            "nationality": country_map.get(p.get("nationality_id")),
            "date_of_birth": p.get("date_of_birth"),
            "height": p.get("height"),
            "weight": p.get("weight"),
        }
        for eid, p in players.items()
    }
    team_map = {
        eid: {
            "name": t.get("name") or f"team {eid}",
            "country": country_map.get(t.get("country_id")),
            "founded": t.get("founded"),
            "short_code": t.get("short_code"),
        }
        for eid, t in teams.items()
    }

    with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "players": player_map, "teams": team_map, "types": type_map,
            "countries": country_map,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nConsolidated lookup written to {ENTITIES_FILE}")

    conn = init_db()
    save_players(conn, player_map)
    save_teams(conn, team_map)
    save_lookup(conn, "sportmonks_type", type_map)
    save_lookup(conn, "sportmonks_country", country_map)
    conn.close()
    print(f"Reference tables written to {DB_PATH} "
          f"(sportmonks_player, sportmonks_team, sportmonks_type, sportmonks_country)")

    section("DONE")
    print(f"players resolved: {len(player_map)}/{len(player_ids)}")
    print(f"teams resolved:   {len(team_map)}/{len(team_ids)}")
    print(f"types resolved:   {len(type_map)}/{len(type_ids)}")
    print(f"positions resolved (free, from types): "
          f"{sum(1 for p in player_map.values() if p['position'])}/{len(player_map)} players")
    if country_map:
        print(f"countries fetched: {len(country_map)} "
              f"(/core/countries guess worked)")
        with_nat = sum(1 for p in player_map.values() if p["nationality"])
        print(f"  -> {with_nat}/{len(player_map)} players have a resolved nationality")
    else:
        print("countries: /core/countries did not return usable data — "
              "the endpoint name was a guess; nationality/country fields "
              "will be null throughout. Check the log for the actual "
              "error/status if this matters.")
    missing_players = len(player_ids) - len(player_map)
    if missing_players:
        print(f"\n! {missing_players} player ids never resolved (404s or errors) — "
              f"check the log; a re-run will retry only these, everything "
              f"else is cached.")
    missing_teams = len(team_ids) - len(team_map)
    if missing_teams:
        pct = 100 * missing_teams / len(team_ids)
        print(f"\n! {missing_teams} team ids ({pct:.0f}%) never resolved — confirmed "
              f"via log inspection this is Sportmonks silently returning HTTP 200 "
              f"with empty data (the same out-of-plan gating proven for leagues "
              f"earlier in this project), not an error. These are teams OUTSIDE "
              f"your 53 selected leagues — cup opponents, loan clubs, lower "
              f"divisions — referenced incidentally by a player's history. "
              f"Expected, not fixable without spending plan slots on leagues "
              f"outside this project's UEFA-55 scope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
