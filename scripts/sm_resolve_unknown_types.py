#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Name the type ids our data references but the cached taxonomy can't resolve.

`ingest/resolve.py` only resolves type ids referenced by *sidelined* records,
so the cached taxonomy is complete for absences and patchy for everything else.
Transfers exposed the gap: type 9688 sits on ~14k rows and is absent from the
bulk `/core/types` response, so those transfers render as "unspecified".

Rather than probing one id by hand, this finds every referenced-but-unnamed id
across absences and transfers, asks the API for each, and (with --write)
appends the results to the cached taxonomy — the same append-back pattern
resolve.py already uses, so a later `python -m app.etl` picks the names up
with no re-fetch.

Costs one Type-bucket call per unknown id, and there are usually very few.

Usage:
    uv run python scripts/sm_resolve_unknown_types.py            # report only
    uv run python scripts/sm_resolve_unknown_types.py --write    # update cache
"""
import argparse
import json
import os
import sqlite3
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = "https://api.sportmonks.com/v3/core"
TYPES_FILE = os.path.join(BASE, "data", "raw", "sportmonks", "types.json")
APP_DB = os.path.join(BASE, "app", "app.db")


def referenced_type_ids(db_path):
    """Every type id the curated database actually points at, and from where."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        sources = {
            "absence": "SELECT DISTINCT type_id FROM absence WHERE type_id IS NOT NULL",
            "transfer": "SELECT DISTINCT type_id FROM transfer WHERE type_id IS NOT NULL",
        }
        return {name: {row[0] for row in connection.execute(sql)}
                for name, sql in sources.items()}
    finally:
        connection.close()


def fetch_type(token, type_id):
    """One type by id. Returns (status, name-or-None).

    A 200 carrying empty `data` is Sportmonks' out-of-plan signal, not a
    missing id — see logbook/sportmonks.md — so it is reported distinctly from
    a real 404.
    """
    response = requests.get(f"{CORE}/types/{type_id}",
                            params={"api_token": token}, timeout=30)
    if response.status_code != 200:
        return response.status_code, None
    data = (response.json() or {}).get("data") or {}
    return 200, data.get("name")


def main():
    parser = argparse.ArgumentParser(description="Resolve unnamed type ids")
    parser.add_argument("--write", action="store_true",
                        help="append newly resolved types to the cached taxonomy")
    parser.add_argument("--db", default=APP_DB, help=f"database to scan (default {APP_DB})")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
    if not token or token.startswith("REPLACE_"):
        print("! SPORTMONKS token not set in .env")
        return 1
    if not os.path.exists(args.db):
        print(f"! no database at {args.db} — run: uv run python -m app.etl")
        return 1

    with open(TYPES_FILE, encoding="utf-8") as handle:
        cached = json.load(handle)
    known = {int(entry["id"]) for entry in cached if entry.get("id") is not None}
    print(f"cached taxonomy: {len(known)} types")

    by_source = referenced_type_ids(args.db)
    unknown = {}
    for source, ids in by_source.items():
        missing = sorted(ids - known)
        print(f"  {source}: {len(ids)} type ids referenced · {len(missing)} unnamed")
        for type_id in missing:
            unknown.setdefault(type_id, []).append(source)

    if not unknown:
        print("\nNothing to resolve — every referenced type already has a name.")
        return 0

    print(f"\nprobing {len(unknown)} unnamed id(s) (Type bucket) …\n")
    resolved = {}
    for type_id, sources in sorted(unknown.items()):
        status, name = fetch_type(token, type_id)
        where = "+".join(sources)
        if name:
            resolved[type_id] = name
            print(f"  {type_id:<6} [{where}]  -> {name!r}")
        elif status == 200:
            # 200 + empty data is the out-of-plan/unknown-to-us signal.
            print(f"  {type_id:<6} [{where}]  -> HTTP 200 but empty: not exposed on this plan")
        else:
            print(f"  {type_id:<6} [{where}]  -> HTTP {status}")

    if not resolved:
        print("\nNone could be named. Leave them rendering as 'unspecified' — that is\n"
              "honest, and better than inferring a label from row shape.")
        return 0

    if args.write:
        cached.extend({"id": tid, "name": name} for tid, name in sorted(resolved.items()))
        with open(TYPES_FILE, "w", encoding="utf-8") as handle:
            json.dump(cached, handle, ensure_ascii=False, indent=2)
        print(f"\nappended {len(resolved)} type(s) -> {os.path.relpath(TYPES_FILE, BASE)}")
        print("Now rebuild so the names reach the app:  uv run python -m app.etl")
    else:
        print(f"\n{len(resolved)} type(s) resolvable. Re-run with --write to cache them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
