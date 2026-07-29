"""The injuries spine — one call per (league, season).

This is the reason the API-Football side of the project exists. Sportmonks has
no bulk injuries endpoint at all: absences there must be reconstructed from
`sidelined` records riding on fixtures, month by month. Here `/injuries` is
addressable directly by league and season, so the entire UEFA injury record
costs roughly one call per covered league-season.

Cache-first and resumable: a cached league-season is skipped, so a re-run only
pays for what is missing.

**Two outcomes are cached, four are not.** `OK` (records found) and `EMPTY`
(vendor genuinely has none) are real answers and are written to disk so a
re-run never pays for them again. `PLAN_BLOCKED`, `AUTH_FAILED`,
`QUOTA_EXHAUSTED` and `ERROR` describe *our* access, not the data — caching
them would freeze a temporary condition into the permanent record and make the
gap invisible to every later run.

**Flag-vs-reality mismatches are reported, not swallowed.** We only fetch pairs
the vendor's own `coverage.injuries` flag marks as covered, so an `EMPTY`
result is a contradiction: the catalogue promised data the endpoint didn't
deliver. That was an explicitly unverified assumption for the 2025 seasons
(see `logbook/apifootball.md`, 2026-07-29), and this runner is what verifies
it. Counting those silently would waste the check.

Usage:
    python -m ingest.apifootball.injuries
    python -m ingest.apifootball.injuries --seasons 2024,2025
    python -m ingest.apifootball.injuries --leagues 39,140 --refresh
    python -m ingest.apifootball.injuries --limit 5      # small trial run
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dotenv import load_dotenv

from ingest.apifootball import paths
from ingest.apifootball.client import EMPTY, OK, ApiFootballClient
from ingest.core.cache import read_cache, write_cache

DEFAULT_CONCURRENCY = 4

# Outcomes that describe the DATA (and so are worth persisting) versus those
# that describe our ACCESS (and so must be retried on a later run).
CACHEABLE = (OK, EMPTY)


def fetch_league_season(client, league_id, season, refresh=False):
    """Fetch one (league, season) injury set.

    Returns (record_count, outcome, detail, from_cache). `detail` carries the
    vendor's own message on failure — without it a caller can only report
    "error" and the reason has to be dug out of the response log, which is
    exactly how long the `page`-field rejection took to spot.

    The raw records are written to disk before returning, so a download is
    never lost to a later failure in the run.
    """
    path = paths.league_season_path(paths.INJURIES_DIR, league_id, season)
    if not refresh:
        cached = read_cache(path)
        if cached is not None:
            return (len(cached.get("injuries", [])), cached.get("outcome", OK),
                    cached.get("detail", ""), True)

    records, outcome, detail, truncated = client.get_all(
        "/injuries", {"league": league_id, "season": season})

    if outcome not in CACHEABLE:
        return None, outcome, detail, False

    write_cache(path, {
        "league_id": league_id,
        "season": season,
        "outcome": outcome,
        "detail": detail,
        "truncated": truncated,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "injuries": records,
    })
    return len(records), outcome, detail, False


def run(client, pairs, concurrency=DEFAULT_CONCURRENCY, refresh=False):
    """Fetch every (league, season) pair, reporting per-outcome totals."""
    outcomes = Counter()
    records_total = 0
    mismatches = []   # flagged as covered, returned nothing
    failures = []     # access problems worth retrying later

    print(f"INJURIES — {len(pairs)} league-seasons, concurrency={concurrency}")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(fetch_league_season, client, league_id, season, refresh):
                (league_id, season, country, league)
            for league_id, season, country, league in pairs
        }
        for done, future in enumerate(as_completed(futures), 1):
            league_id, season, country, league = futures[future]
            count, outcome, detail, from_cache = future.result()
            outcomes[("cached" if from_cache else outcome)] += 1
            if count:
                records_total += count
            label = f"{country} · {league} {season}"
            if outcome == EMPTY:
                mismatches.append(label)
            elif outcome not in CACHEABLE:
                # Carry the vendor's message: "error" alone sends the reader to
                # the log, and the reason is usually right here.
                failures.append(f"{label}: {outcome} — {detail}" if detail
                                else f"{label}: {outcome}")
            if done % 10 == 0 or done == len(pairs):
                print(f"\r  {done}/{len(pairs)} · {records_total:,} records",
                      end="", flush=True)

    print(f"\n\n  outcomes: {dict(outcomes)}")
    print(f"  injury records fetched/cached: {records_total:,}")

    if mismatches:
        # The vendor's catalogue and its data disagree. Not an error on our
        # side, but it means the coverage flag overstates what is available.
        print(f"\n  ! {len(mismatches)} league-season(s) flagged as covered "
              f"returned ZERO records:")
        for label in sorted(mismatches)[:20]:
            print(f"      {label}")
        if len(mismatches) > 20:
            print(f"      … and {len(mismatches) - 20} more")
        print("    Record this in logbook/apifootball.md — it qualifies the "
              "coverage flag's accuracy.")

    if failures:
        print(f"\n  ! {len(failures)} access failure(s) — NOT cached, "
              f"re-run to retry:")
        for label in sorted(failures)[:20]:
            print(f"      {label}")

    return {"outcomes": dict(outcomes), "records": records_total,
            "mismatches": mismatches, "failures": failures}


def make_client(name):
    load_dotenv()
    key = os.getenv("APIFOOTBALL_KEY")
    if not key or key.startswith("REPLACE_"):
        print("! APIFOOTBALL_KEY not set in .env")
        return None
    os.makedirs(paths.LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(paths.LOG_DIR, f"apifootball-{name}.{stamp}.log")
    print(f"logging responses -> {log_path}")
    return ApiFootballClient(key, log_path=log_path)


def select_pairs(args):
    """The (league, season) work list, narrowed by any CLI filters."""
    pairs = paths.covered_league_seasons()
    if args.leagues:
        wanted = {int(part) for part in args.leagues.split(",") if part.strip()}
        pairs = [p for p in pairs if p[0] in wanted]
        unknown = wanted - {p[0] for p in pairs}
        if unknown:
            # Loudly: a typo'd id would otherwise just narrow the run and look
            # like a successful smaller one.
            print(f"! not in the coverage work list, ignoring: {sorted(unknown)}")
    if args.seasons:
        wanted = {int(part) for part in args.seasons.split(",") if part.strip()}
        pairs = [p for p in pairs if p[1] in wanted]
    if args.limit:
        pairs = pairs[:args.limit]
    return pairs


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch API-Football injuries per league-season")
    parser.add_argument("--leagues", help="comma-separated league ids (default: all covered)")
    parser.add_argument("--seasons", help="comma-separated season years (default: all covered)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"concurrent in-flight requests (default {DEFAULT_CONCURRENCY}); "
                             f"the client paces these under the per-minute ceiling")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and re-fetch every league-season")
    parser.add_argument("--limit", type=int, help="stop after N league-seasons (trial run)")
    args = parser.parse_args(argv)

    pairs = select_pairs(args)
    if not pairs:
        print("! no league-seasons selected — nothing to fetch")
        return 1

    client = make_client("injuries")
    if client is None:
        return 1

    # Pre-flight budget check. Cached pairs cost nothing, but we cannot know
    # which are cached without stat-ing them, so this deliberately assumes the
    # worst case rather than under-reporting the cost of the run.
    affordable, remaining = client.can_afford(len(pairs))
    if not affordable:
        print(f"! this run needs up to {len(pairs)} calls but only {remaining} "
              f"remain in today's quota. It will stop partway.\n"
              f"  Narrow it with --leagues/--seasons/--limit, or wait for the "
              f"daily reset. Continuing — Ctrl-C to abort.")

    run(client, pairs, args.concurrency, args.refresh)
    print(f"\nquota: {client.quota()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
