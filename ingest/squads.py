"""Capture squad rosters — one bulk call per team.

`/squads/teams/{id}` returns a team's roster as player *stints* (player_id,
position, jersey, captain, start/end dates), probe-confirmed in-plan. One call
per team, so ~800 calls for our cached teams — far cheaper than the
per-(team, season) endpoint, and largely complementary: the injured players'
own team history is already captured via the `teams` include on the player
enrichment pass, so this fills in per-team rosters (including players who never
got injured) rather than being the primary membership source.

Resumable: a team whose squad is already cached is skipped. Squad calls bill
their own quota bucket, so this can run alongside the player/fixture enrichment
passes without competing.

Usage:
    python -m ingest.squads
"""
from __future__ import annotations

import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from ingest import paths
from ingest.backfill import make_client
from ingest.sportmonks_client import read_cache, write_cache


def cached_team_ids():
    """Team ids we've already resolved — the set worth fetching squads for."""
    ids = []
    for path in glob.glob(os.path.join(paths.TEAMS_DIR, "*.json")):
        name = os.path.splitext(os.path.basename(path))[0]
        if name.isdigit():
            ids.append(int(name))
    return ids


def fetch_squad(client, team_id):
    """Cache one team's squad. Returns 'cached' | 'fetched' | 'failed'."""
    path = paths.squad_cache_path(team_id)
    if read_cache(path) is not None:
        return "cached"
    status, body = client.get(f"{paths.FOOTBALL}/squads/teams/{team_id}")
    if status != 200:
        return "failed"
    # An empty list is a valid answer (team in plan, no roster returned) — cache
    # it so a re-run doesn't keep retrying a team that simply has no squad data.
    write_cache(path, {"team_id": team_id, "squad": (body or {}).get("data") or []})
    return "fetched"


def run(client, concurrency):
    os.makedirs(paths.SQUADS_DIR, exist_ok=True)
    team_ids = cached_team_ids()
    print(f"SQUADS — {len(team_ids)} teams to cover")
    totals = {"fetched": 0, "cached": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(fetch_squad, client, team_id): team_id for team_id in team_ids}
        for done, future in enumerate(as_completed(futures), 1):
            totals[future.result()] += 1
            if done % 50 == 0 or done == len(team_ids):
                print(f"\r  {done}/{len(team_ids)}  "
                      f"fetched={totals['fetched']} cached={totals['cached']} "
                      f"failed={totals['failed']}", end="", flush=True)
    print(f"\n  done: {totals}")
    return totals


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Fetch squad rosters per team")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="concurrent in-flight requests (default 3)")
    args = parser.parse_args(argv)

    client = make_client("squads")
    if client is None:
        return 1
    run(client, args.concurrency)
    print(f"\nquota remaining by entity: {client.quota_snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
