"""League-season and team-season crawl — everything except per-fixture detail.

One runner for the endpoints addressable by (league, season): fixtures, teams,
standings, players; plus team statistics, which is per (league, season, team)
and derived from the teams cache.

Cache-first and resumable throughout: a cached response is skipped, so a re-run
costs only what is missing. Nothing here re-fetches.

**Quota-aware stop.** The daily budget is 7,500 and a full crawl is larger than
that, so exhausting it is a normal outcome, not an error. When the vendor
reports the day's limit reached, the run stops cleanly, reports how far it got,
and exits — every completed fetch is already on disk, and tomorrow's run picks
up exactly where this one stopped. Retrying inside the run would be pointless:
the window is hours long, not seconds.

Usage:
    python -m ingest.apifootball.crawl --target fixtures
    python -m ingest.apifootball.crawl --target tier1     # fixtures+teams+standings
    python -m ingest.apifootball.crawl --target players
    python -m ingest.apifootball.crawl --target team-stats
    python -m ingest.apifootball.crawl --target all
    python -m ingest.apifootball.crawl --target all --dry-run   # cost only
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ingest.apifootball import paths
from ingest.apifootball.client import (
    CACHEABLE_OUTCOMES, STOP_OUTCOMES, ApiFootballClient)
from ingest.apifootball.injuries import make_client
from ingest.core.cache import read_cache, write_cache

DEFAULT_CONCURRENCY = 4

# Endpoint specs for the (league, season) targets. `key` names the field the
# cached document stores its records under, so the ETL and any inspection
# script can find them without knowing the endpoint.
# `pages` is the expected number of HTTP calls per item. It is 1 for the
# endpoints that return a whole league-season in one response, but /players
# paginates at ~20 records a page, so one league-season there costs tens of
# calls. Without this the cost estimate under-reports players by ~25x.
LEAGUE_SEASON_TARGETS = {
    "fixtures":  {"path": "/fixtures",  "dir": paths.FIXTURES_DIR,  "key": "fixtures",  "pages": 1},
    "teams":     {"path": "/teams",     "dir": paths.TEAMS_DIR,     "key": "teams",     "pages": 1},
    "standings": {"path": "/standings", "dir": paths.STANDINGS_DIR, "key": "standings", "pages": 1},
    "players":   {"path": "/players",   "dir": paths.PLAYERS_DIR,   "key": "players",   "pages": 25},
}

TIER1 = ("fixtures", "teams", "standings")


class QuotaStop(threading.Event):
    """Set once the vendor reports the daily budget spent.

    Workers check it before starting, so a run winds down promptly instead of
    firing hundreds more requests that will all come back exhausted.
    """


def fetch_league_season(client, spec, league_id, season, stop, refresh=False):
    """Fetch one (league, season) for one endpoint. Returns (count, outcome)."""
    if stop.is_set():
        return None, "skipped"
    path = paths.league_season_path(spec["dir"], league_id, season)
    if not refresh:
        cached = read_cache(path)
        if cached is not None:
            return len(cached.get(spec["key"], [])), "cached"

    records, outcome, detail, truncated = client.get_all(
        spec["path"], {"league": league_id, "season": season})

    if outcome in STOP_OUTCOMES:
        stop.set()
        return None, outcome
    if outcome not in CACHEABLE_OUTCOMES:
        return None, outcome

    write_cache(path, {
        "league_id": league_id, "season": season, "outcome": outcome,
        "detail": detail, "truncated": truncated,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        spec["key"]: records,
    })
    return len(records), outcome


def fetch_team_season(client, league_id, season, team_id, stop, refresh=False):
    """Fetch one team's season statistics. Returns (count, outcome)."""
    if stop.is_set():
        return None, "skipped"
    path = paths.team_season_path(league_id, season, team_id)
    if not refresh and read_cache(path) is not None:
        return 1, "cached"

    status, body, outcome, detail = client.get(
        "/teams/statistics",
        {"league": league_id, "season": season, "team": team_id})

    if outcome in STOP_OUTCOMES:
        stop.set()
        return None, outcome
    if outcome not in CACHEABLE_OUTCOMES:
        return None, outcome

    write_cache(path, {
        "league_id": league_id, "season": season, "team_id": team_id,
        "outcome": outcome, "detail": detail,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statistics": (body or {}).get("response"),
    })
    return 1, outcome


def truncated_pairs(target):
    """(league_id, season) pairs whose cached file for `target` is incomplete.

    Lets a re-fetch target exactly the broken files instead of refreshing all
    117 — the difference between ~20 calls' worth of work and re-buying the
    whole target.
    """
    spec = LEAGUE_SEASON_TARGETS[target]
    pairs = []
    for path in sorted(glob.glob(os.path.join(spec["dir"], "*.json"))):
        document = read_cache(path) or {}
        if document.get("truncated"):
            pairs.append((document.get("league_id"), document.get("season")))
    return [p for p in pairs if p[0] is not None and p[1] is not None]


def report_truncation(targets):
    """Warn about any cached file that hit get_all's max_pages ceiling.

    `truncated` has always been recorded in the cache but never surfaced, which
    made an incomplete fetch indistinguishable from a small one — the exact
    failure the project's "every capped list returns its real total" convention
    exists to prevent. /players paginates ~20 records a page, so a league-season
    with more than max_pages x 20 players would silently under-collect.

    Scans the cache rather than tracking it per-run, so truncation from ANY
    earlier run is caught too, not just the one that just finished.
    """
    flagged = []
    for name in targets:
        spec = LEAGUE_SEASON_TARGETS[name]
        for path in sorted(glob.glob(os.path.join(spec["dir"], "*.json"))):
            document = read_cache(path) or {}
            if document.get("truncated"):
                flagged.append(f"{name}: {os.path.basename(path)} "
                               f"({len(document.get(spec['key']) or [])} records)")
    if flagged:
        print(f"\n! {len(flagged)} cached file(s) were TRUNCATED at the "
              f"pagination ceiling — these are incomplete:")
        for line in flagged[:20]:
            print(f"    {line}")
        if len(flagged) > 20:
            print(f"    … and {len(flagged) - 20} more")
        print("  Re-fetch with a higher max_pages, or the counts understate "
              "reality.")
    return flagged


def cached_team_seasons():
    """Every (league, season, team) triple implied by the cached teams files.

    Derived from the teams cache rather than a separate fetch — which is why
    `--target teams` must run before `--target team-stats`. A missing teams
    cache yields an empty work list, so the runner says so rather than
    reporting a successful zero-work run.
    """
    triples = []
    for path in sorted(glob.glob(os.path.join(paths.TEAMS_DIR, "*.json"))):
        document = read_cache(path) or {}
        league_id, season = document.get("league_id"), document.get("season")
        if league_id is None or season is None:
            continue
        for entry in document.get("teams") or []:
            team = (entry or {}).get("team") or {}
            if team.get("id"):
                triples.append((league_id, season, team["id"]))
    return triples


def run_pool(jobs, worker, concurrency, label, stop):
    """Run `jobs` through `worker` concurrently, reporting outcome totals."""
    outcomes, records = Counter(), 0
    print(f"\n{label} — {len(jobs)} to do, concurrency={concurrency}")
    if not jobs:
        return {"outcomes": {}, "records": 0}
    # Report ~20 times per target regardless of size. A fixed stride is wrong
    # here because one job is not one call: a paginated /players job is ~25
    # requests, so a stride of 25 means minutes of total silence — which reads
    # as a hang. (Exactly the failure logbook/sportmonks.md records for an
    # early batch script.)
    stride = max(1, min(25, len(jobs) // 20))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            count, outcome = future.result()
            outcomes[outcome] += 1
            if count:
                records += count
            if done % stride == 0 or done == len(jobs):
                print(f"\r  {done}/{len(jobs)} · {records:,} records "
                      f"· {dict(outcomes)}", end="", flush=True)
    print()
    if stop.is_set():
        print("  ! daily quota exhausted — run stopped early. Everything "
              "fetched is cached;\n    re-run tomorrow to continue exactly "
              "where this left off.")
    return {"outcomes": dict(outcomes), "records": records}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="API-Football league-season and team-season crawl")
    parser.add_argument("--target", default="tier1",
                        choices=list(LEAGUE_SEASON_TARGETS) + ["tier1", "team-stats", "all"],
                        help="what to fetch (default tier1: fixtures+teams+standings)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    parser.add_argument("--refresh-truncated", action="store_true",
                        help="re-fetch ONLY the cached files that hit the "
                             "pagination ceiling and are therefore incomplete")
    parser.add_argument("--limit", type=int, help="stop after N items (trial run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what WOULD be fetched, make no calls")
    args = parser.parse_args(argv)

    pairs = paths.covered_league_seasons()
    if args.limit:
        pairs = pairs[:args.limit]

    targets = (TIER1 if args.target == "tier1"
               else list(LEAGUE_SEASON_TARGETS) if args.target == "all"
               else [] if args.target == "team-stats"
               else [args.target])
    wants_team_stats = args.target in ("team-stats", "all")

    if args.dry_run:
        print(f"\ndry run — {len(pairs)} league-seasons\n")
        total = 0
        for name in targets:
            spec = LEAGUE_SEASON_TARGETS[name]
            missing = sum(1 for lid, season, _c, _l in pairs
                          if read_cache(paths.league_season_path(
                              spec["dir"], lid, season)) is None)
            calls = missing * spec["pages"]
            total += calls
            note = (f"  ~{spec['pages']} calls each (paginated)"
                    if spec["pages"] > 1 else "")
            print(f"  {name:12} {missing:>6,} to fetch → ~{calls:>6,} calls "
                  f"({len(pairs) - missing:,} cached){note}")
        if wants_team_stats:
            triples = cached_team_seasons()
            missing = sum(1 for lid, s, t in triples
                          if read_cache(paths.team_season_path(lid, s, t)) is None)
            total += missing
            print(f"  {'team-stats':12} {missing:>6,} to fetch "
                  f"({len(triples) - missing:,} cached)")
            if not triples:
                print("               (none — run `--target teams` first)")
        print(f"\n  total calls: ~{total:,}  ≈ {total / 7500:.1f} day(s) of quota")
        return 0

    client = make_client("crawl")
    if client is None:
        return 1
    stop = QuotaStop()

    for name in targets:
        spec = LEAGUE_SEASON_TARGETS[name]
        if args.refresh_truncated:
            jobs = truncated_pairs(name)
            if not jobs:
                print(f"\n{name.upper()} — no truncated files, nothing to redo")
                continue
        else:
            jobs = [(lid, season) for lid, season, _c, _l in pairs]
        # refresh_truncated implies bypassing the cache: those files exist, they
        # are just incomplete, so a cache-first fetch would skip them entirely.
        force = args.refresh or args.refresh_truncated
        run_pool(
            jobs,
            lambda job: fetch_league_season(client, spec, job[0], job[1], stop,
                                            force),
            args.concurrency, name.upper(), stop)
        if stop.is_set():
            break

    if wants_team_stats and not stop.is_set():
        triples = cached_team_seasons()
        if not triples:
            print("\nTEAM-STATS — no teams cached; run `--target teams` first.")
        else:
            run_pool(
                triples,
                lambda job: fetch_team_season(client, job[0], job[1], job[2],
                                              stop, args.refresh),
                args.concurrency, "TEAM-STATS", stop)

    report_truncation([t for t in targets])
    print(f"\nquota: {client.quota()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
