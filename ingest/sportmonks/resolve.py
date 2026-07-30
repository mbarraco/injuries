"""Resolve the numeric ids in cached fixtures into names + enrichment.

Every `sidelined` record in the fixture cache carries only player_id,
team_id and type_id. This module turns those into the reference tables
`app/etl.py` reads from `coverage.db` (sportmonks_player / _team / _type /
_country), plus a consolidated `data/reference/sportmonks/entities.json`.

Resolution is cache-first and rebuilt from the full on-disk cache every run:
- Types: one cheap bulk fetch of `/core/types`, then per-id fallback for the
  ids that bulk list omits (confirmed: the list tops out ~id 595 but real
  referenced ids run past 2000; direct lookup resolves the rest). Newly
  resolved types are appended back into the cached list so a re-run is free.
- Countries: one bulk fetch of `/core/countries` (resolves nationality).
- Positions: free — they're just `/core/types` rows with model_type
  "position", no extra calls.
- Players / Teams: fetched per id and cached individually. The path-based
  `/multi/` batch endpoint does NOT work for these two (proven earlier), so
  per-id is the only reliable path — Player and Team each have their own
  hourly quota bucket, separate from Fixture, so this never competes with a
  fixture sweep.

Out-of-plan ids return HTTP 200 with empty `data`, not 403 — those simply
stay unresolved (expected for cup opponents / lower divisions referenced
incidentally), and the raw id is still stored so nothing is silently lost.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from ingest.core.cache import read_cache, write_cache
from ingest.sportmonks import paths
from ingest.sportmonks.client import PLAYER, TEAM


def _section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# --------------------------------------------------------------------------- #
# 1. Scan the fixture cache for every referenced id.
# --------------------------------------------------------------------------- #
def scan_referenced_ids(fixtures_dir=None):
    fixtures_dir = fixtures_dir or paths.FIXTURES_DIR
    player_ids, team_ids, type_ids = set(), set(), set()
    files = sorted(glob.glob(os.path.join(fixtures_dir, "*.json")))
    for path in files:
        document = read_cache(path) or {}
        for fixture in document.get("fixtures", []):
            for pivot in fixture.get("sidelined") or []:
                sideline = pivot.get("sideline") or {}
                if sideline.get("player_id"):
                    player_ids.add(sideline["player_id"])
                if sideline.get("team_id"):
                    team_ids.add(sideline["team_id"])
                for source in (sideline, pivot):
                    if source.get("type_id"):
                        type_ids.add(source["type_id"])
                if pivot.get("player_id"):
                    player_ids.add(pivot["player_id"])
    print(f"scanned {len(files)} fixture files · {len(player_ids)} players · "
          f"{len(team_ids)} teams · {len(type_ids)} types referenced")
    return player_ids, team_ids, type_ids


# --------------------------------------------------------------------------- #
# 2. Types (bulk once, per-id fallback) and countries (bulk once).
# --------------------------------------------------------------------------- #
def _fetch_bulk_list(client, url, cache_file, label):
    cached = read_cache(cache_file)
    if cached is not None:
        print(f"  using cached {label} ({len(cached)} rows)")
        return cached
    status, items, _truncated, _first = client.get_all(url)
    if status != 200:
        print(f"  ! {label} bulk fetch -> HTTP {status}; leaving unresolved")
        return []
    write_cache(cache_file, items)
    print(f"  fetched {len(items)} {label} -> cached {cache_file}")
    return items


def resolve_types(client, referenced_ids, concurrency):
    _section("TYPES")
    raw_types = _fetch_bulk_list(client, f"{paths.CORE}/types", paths.TYPES_FILE, "types")
    type_map = {int(row["id"]): row["name"] for row in raw_types if row.get("id")}

    missing = sorted(referenced_ids - set(type_map))
    if missing:
        print(f"  {len(missing)} referenced ids absent from the bulk list; "
              f"resolving individually …")
        newly = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(client.get, f"{paths.CORE}/types/{tid}"): tid
                       for tid in missing}
            for future in as_completed(futures):
                tid = futures[future]
                status, body = future.result()
                data = (body or {}).get("data") or {}
                if status == 200 and data.get("name"):
                    newly[tid] = data["name"]
        if newly:
            type_map.update(newly)
            existing_ids = {row["id"] for row in raw_types}
            raw_types.extend({"id": tid, "name": name}
                             for tid, name in newly.items() if tid not in existing_ids)
            write_cache(paths.TYPES_FILE, raw_types)
            print(f"  resolved {len(newly)} extra types (appended to cache)")

    positions = {row["id"]: row["name"]
                 for row in raw_types if row.get("model_type") == "position"}
    return type_map, positions


def resolve_countries(client):
    _section("COUNTRIES")
    raw = _fetch_bulk_list(client, f"{paths.CORE}/countries", paths.COUNTRIES_FILE, "countries")
    return {int(row["id"]): row["name"] for row in raw if row.get("id")}


# --------------------------------------------------------------------------- #
# 3. Players / teams — per-id, cache-first.
# --------------------------------------------------------------------------- #
def resolve_entities(client, kind, endpoint, ids, concurrency, quota_entity=None):
    """Fetch each id once, caching its raw JSON; skip ids already cached.

    `quota_entity` is the rate_limit bucket these ids bill against (e.g.
    "Player") — passed so we can pause up front if that bucket is already
    exhausted, without touching the separate Fixture bucket.
    """
    _section(f"{kind.upper()} — {len(ids)} referenced")
    cached, todo = {}, []
    for entity_id in ids:
        path = paths.entity_cache_path(kind, entity_id)
        existing = read_cache(path)
        if existing is not None:
            cached[entity_id] = existing
        else:
            todo.append(entity_id)
    print(f"  {len(cached)} already cached · {len(todo)} to fetch")
    if not todo:
        return cached

    if quota_entity:
        client.await_quota(quota_entity)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(client.get, f"{paths.FOOTBALL}{endpoint}/{entity_id}"): entity_id
                   for entity_id in todo}
        done = 0
        for future in as_completed(futures):
            entity_id = futures[future]
            status, body = future.result()
            done += 1
            if done % 50 == 0 or done == len(todo):
                print(f"\r  fetched {done}/{len(todo)}", end="", flush=True)
            data = (body or {}).get("data") or {}
            if status != 200 or not data:
                continue  # out-of-plan/dead id: leave unresolved, id still stored
            write_cache(paths.entity_cache_path(kind, entity_id), data)
            cached[entity_id] = data
    print()
    return cached


# --------------------------------------------------------------------------- #
# 4. Enrichment + coverage.db reference tables.
# --------------------------------------------------------------------------- #
def _player_row(entity_id, raw, positions, countries):
    return {
        "name": raw.get("display_name") or raw.get("name") or f"player {entity_id}",
        "position": positions.get(raw.get("position_id")),
        "detailed_position": positions.get(raw.get("detailed_position_id")),
        "nationality": countries.get(raw.get("nationality_id")),
        "date_of_birth": raw.get("date_of_birth"),
        "height": raw.get("height"),
        "weight": raw.get("weight"),
        "image_path": raw.get("image_path"),
    }


def _team_row(entity_id, raw, countries):
    return {
        "name": raw.get("name") or f"team {entity_id}",
        "country": countries.get(raw.get("country_id")),
        "founded": raw.get("founded"),
        "short_code": raw.get("short_code"),
    }


def write_reference_tables(player_map, team_map, type_map, country_map, db_path=None):
    """Rebuild the sportmonks_* reference tables from the full resolved set.

    Fully rebuilt each run (not incrementally patched): the per-entity JSON
    cache on disk is the source of truth, so there is no state in these
    tables worth preserving across a run.
    """
    connection = sqlite3.connect(db_path or paths.COVERAGE_DB)
    try:
        connection.executescript("""
            DROP TABLE IF EXISTS sportmonks_player;
            DROP TABLE IF EXISTS sportmonks_team;
            CREATE TABLE sportmonks_player (
                id TEXT PRIMARY KEY, name TEXT, position TEXT, detailed_position TEXT,
                nationality TEXT, date_of_birth TEXT, height_cm INTEGER, weight_kg INTEGER,
                image_path TEXT);
            CREATE TABLE sportmonks_team (
                id TEXT PRIMARY KEY, name TEXT, country TEXT, founded INTEGER, short_code TEXT);
            CREATE TABLE IF NOT EXISTS sportmonks_type    (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE IF NOT EXISTS sportmonks_country (id TEXT PRIMARY KEY, name TEXT);
        """)
        connection.executemany(
            "INSERT OR REPLACE INTO sportmonks_player VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(str(eid), row["name"], row["position"], row["detailed_position"],
              row["nationality"], row["date_of_birth"], row["height"], row["weight"],
              row["image_path"])
             for eid, row in player_map.items()])
        connection.executemany(
            "INSERT OR REPLACE INTO sportmonks_team VALUES (?, ?, ?, ?, ?)",
            [(str(eid), row["name"], row["country"], row["founded"], row["short_code"])
             for eid, row in team_map.items()])
        connection.executemany(
            "INSERT OR REPLACE INTO sportmonks_type VALUES (?, ?)",
            [(str(eid), name) for eid, name in type_map.items()])
        connection.executemany(
            "INSERT OR REPLACE INTO sportmonks_country VALUES (?, ?)",
            [(str(eid), name) for eid, name in country_map.items()])
        connection.commit()
    finally:
        connection.close()


def run(client, concurrency=3, fixtures_dir=None):
    """Resolve everything referenced by the current fixture cache.

    Safe to call at the end of any fetch run — it rebuilds the reference
    tables from whatever is on disk, so partial fetches still produce a
    consistent, queryable result.
    """
    player_ids, team_ids, type_ids = scan_referenced_ids(fixtures_dir)
    type_map, positions = resolve_types(client, type_ids, concurrency)
    country_map = resolve_countries(client)
    players = resolve_entities(client, "players", "/players", player_ids, concurrency,
                               quota_entity=PLAYER)
    teams = resolve_entities(client, "teams", "/teams", team_ids, concurrency,
                             quota_entity=TEAM)

    player_map = {eid: _player_row(eid, raw, positions, country_map)
                  for eid, raw in players.items()}
    team_map = {eid: _team_row(eid, raw, country_map) for eid, raw in teams.items()}
    type_map = {tid: name for tid, name in type_map.items() if tid in type_ids}

    write_cache(paths.ENTITIES_FILE, {
        "players": player_map, "teams": team_map,
        "types": type_map, "countries": country_map,
    })
    write_reference_tables(player_map, team_map, type_map, country_map)

    _section("RESOLVE DONE")
    print(f"players resolved: {len(player_map)}/{len(player_ids)}")
    print(f"teams resolved:   {len(team_map)}/{len(team_ids)}")
    print(f"types resolved:   {len(type_map)}/{len(type_ids)}")
    return {"players": len(player_map), "teams": len(team_map), "types": len(type_map)}
