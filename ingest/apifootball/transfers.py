"""Career transfers — the only API-Football endpoint that escapes the 2020–2025 cap.

Every other endpoint on this vendor is hard-capped at 2020–2025. `/transfers`
is not: 51% of the rows in the probe sample predate 2020, reaching back to the
1920s (logbook 2026-07-30). Pre-2020 career history is not obtainable from this
vendor by any other route, which is why this crawl is worth its quota even
though transfers are not injuries.

**Two subjects, neither redundant.** Measured, not assumed:

| subject | calls | what it gets |
|---|---|---|
| `?team=`   | ~845 | every move in/out of one club, all history |
| `?player=` | tens of thousands | one player's *complete* career |

`?team=` is **club-scoped** — 704 of 704 Ajax rows touch Ajax — so it does not
return the wider careers of the players it names. It is still the right thing to
run first: one Ajax call returned 333 player envelopes against the 152 players
`af_player_season` holds for that club, so it is both absurdly cheap and
*wider* than our own player dimension.

**That width is the point of the cascade.** The team pass discovers player ids
that no other endpoint in this project has ever seen — players who moved
through our clubs but never accumulated statistics in a covered league-season.
`--include-discovered` folds them into the player work list, so the player pass
covers strictly more than `/players` could ever name. Ordering matters: run
`--target team` first, or the discovery set is empty and the run looks complete.

**`page` is rejected.** `/transfers?player=X&page=2` returns HTTP 200 with
`errors: {"page": "The Page field do not exist."}`, same as `/injuries`. So this
uses `client.get`, not `client.get_all`. `paging.total` is recorded anyway: it
was 1 on every probe response, and a file where it is not 1 is the only warning
we would ever get that the assumption broke.

Cache-first and resumable throughout; the daily quota running out is a clean
stop, not a failure.

Usage:
    python -m ingest.apifootball.transfers --dry-run
    python -m ingest.apifootball.transfers --target team
    python -m ingest.apifootball.transfers --target player --include-discovered
    python -m ingest.apifootball.transfers --target all --include-discovered
    python -m ingest.apifootball.transfers --target player --max-calls 10000
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ingest.apifootball import paths
from ingest.apifootball.client import CACHEABLE_OUTCOMES, STOP_OUTCOMES
from ingest.apifootball.injuries import make_client
from ingest.core.cache import read_cache, write_cache

DEFAULT_CONCURRENCY = 4

SUBJECTS = {
    "team":   {"param": "team",   "dir": paths.TRANSFERS_TEAM_DIR},
    "player": {"param": "player", "dir": paths.TRANSFERS_PLAYER_DIR},
}

# Team before player, and not alphabetically: the team pass is ~845 calls and
# feeds the player work list, so an interrupted `all` run should always have
# bought the cheap wide pass before starting the expensive deep one.
SUBJECT_ORDER = ("team", "player")


# --------------------------------------------------------------------------- #
# Work lists, all derived from the raw cache rather than apifootball.db.
#
# The database is a rebuildable artifact that may not exist yet, or may be
# mid-rebuild; the cache is the durable record. Every other runner here reads
# the cache for the same reason, and mixing the two would make a crawl's
# coverage depend on when the ETL last ran.
# --------------------------------------------------------------------------- #
def cached_team_ids():
    """Every team id named by the cached /teams files."""
    ids = set()
    for path in sorted(glob.glob(os.path.join(paths.TEAMS_DIR, "*.json"))):
        for entry in (read_cache(path) or {}).get("teams") or []:
            team = (entry or {}).get("team") or {}
            if team.get("id"):
                ids.add(team["id"])
    return sorted(ids)


def cached_player_ids():
    """Player ids from /players AND from /injuries.

    The union matters. `/players` only returns players who accumulated
    statistics in a covered league-season, so a player injured for a whole
    season is absent from it — the 120 "orphan players" the ETL already reports.
    They have careers too, and a transfer crawl driven by `/players` alone would
    silently skip exactly the players this project is about.
    """
    ids = set()
    for path in sorted(glob.glob(os.path.join(paths.PLAYERS_DIR, "*.json"))):
        for entry in (read_cache(path) or {}).get("players") or []:
            player = (entry or {}).get("player") or {}
            if player.get("id"):
                ids.add(player["id"])
    from_players = len(ids)

    for path in sorted(glob.glob(os.path.join(paths.INJURIES_DIR, "*.json"))):
        for record in (read_cache(path) or {}).get("injuries") or []:
            player = (record or {}).get("player") or {}
            if player.get("id"):
                ids.add(player["id"])
    return sorted(ids), from_players, len(ids) - from_players


def discovered_player_ids():
    """Player ids named by cached TEAM transfer files.

    The cascade. These are players who passed through one of our 845 clubs at
    some point in history — including long before 2020 and including spells at
    clubs far outside the 47 competitions. `/players`, `/injuries` and
    `/fixtures` cannot name them, because none of those reach back that far.

    Empty until `--target team` has run, which is why the runner says so
    explicitly rather than reporting a successful zero-discovery pass.
    """
    ids = set()
    for path in glob.glob(os.path.join(paths.TRANSFERS_TEAM_DIR, "*", "*.json")):
        for entry in (read_cache(path) or {}).get("transfers") or []:
            player = (entry or {}).get("player") or {}
            if player.get("id"):
                ids.add(player["id"])
    return ids


def build_work_list(subject, include_discovered=False):
    """(ids, note) for one subject — the full universe, before cache filtering."""
    if subject == "team":
        ids = cached_team_ids()
        if not ids:
            return [], ("no teams cached — run this first:\n"
                        "    uv run python -m ingest.apifootball.crawl --target teams")
        return ids, f"{len(ids):,} clubs from the /teams cache"

    known, from_players, from_injuries = cached_player_ids()
    note = (f"{len(known):,} players — {from_players:,} from /players "
            f"+ {from_injuries:,} only ever seen in /injuries")
    if not include_discovered:
        return known, (note + "\n    (pass --include-discovered to add players "
                              "named only by team transfer files)")

    discovered = discovered_player_ids()
    if not discovered:
        return known, note + ("\n    ! --include-discovered found nothing: no "
                              "team transfer files cached yet.\n      Run "
                              "`--target team` first, or the cascade is a no-op.")
    fresh = discovered - set(known)
    merged = sorted(set(known) | discovered)
    return merged, (note + f"\n    + {len(fresh):,} NEW players discovered in "
                    f"team transfer files that no other endpoint names "
                    f"→ {len(merged):,} total")


def missing(subject, ids):
    """Ids with no cached file yet — the real work list."""
    directory = SUBJECTS[subject]["dir"]
    return [i for i in ids
            if not os.path.exists(paths.subject_path(directory, i))]


# --------------------------------------------------------------------------- #
# Fetching.
# --------------------------------------------------------------------------- #
def fetch_one(client, subject, subject_id, stop, refresh=False):
    """Fetch one subject's transfers. Returns (move_count, outcome)."""
    if stop.is_set():
        return None, "skipped"
    spec = SUBJECTS[subject]
    path = paths.subject_path(spec["dir"], subject_id)
    if not refresh and os.path.exists(path):
        return None, "cached"

    # client.get, NOT get_all: `page` is rejected outright by this endpoint.
    status, body, outcome, detail = client.get(
        "/transfers", {spec["param"]: subject_id})

    if outcome in STOP_OUTCOMES:
        stop.set()
        return None, outcome
    if outcome not in CACHEABLE_OUTCOMES:
        # Access failures are never cached — caching one would freeze a
        # temporary condition into the permanent record and make the gap
        # invisible to every later run.
        return None, outcome

    records = (body or {}).get("response") or []
    paging = (body or {}).get("paging") or {}
    write_cache(path, {
        "subject": subject, "subject_id": subject_id, "outcome": outcome,
        "detail": detail,
        # Recorded because `page` is rejected, so there is no way to fetch a
        # second page even if one existed. A value other than 1 is the only
        # signal that this endpoint started paginating after all.
        "paging_total": paging.get("total"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "transfers": records,
    })
    return sum(len((e or {}).get("transfers") or []) for e in records), outcome


def report_paging_anomalies():
    """Any cached transfer file whose paging.total was not 1.

    The `page` field is rejected by this endpoint, so a multi-page response
    would be unfetchable AND undetectable — the file would just hold the first
    page and look complete. This is the check that makes that visible, and it
    scans the whole cache so an anomaly from any earlier run is caught too.

    Same failure mode as the `truncated` flag on /players, which was recorded
    faithfully for weeks and never read: ~18,500 player-seasons went missing
    behind a field nothing looked at.
    """
    flagged = []
    for subject, spec in SUBJECTS.items():
        for path in glob.glob(os.path.join(spec["dir"], "*", "*.json")):
            document = read_cache(path) or {}
            total = document.get("paging_total")
            if total not in (None, 0, 1):
                flagged.append(f"{subject} {document.get('subject_id')}: "
                               f"paging.total={total}")
    if flagged:
        print(f"\n! {len(flagged)} transfer file(s) report MORE THAN ONE PAGE, "
              f"and `page` is rejected by this endpoint —\n  these are "
              f"incomplete and there is currently no way to fetch the rest:")
        for line in flagged[:20]:
            print(f"    {line}")
        if len(flagged) > 20:
            print(f"    … and {len(flagged) - 20} more")
    return flagged


def run_subject(client, subject, ids, concurrency, stop, refresh=False,
                max_calls=None):
    """Crawl one subject across the ids still missing a cached file."""
    todo = missing(subject, ids) if not refresh else list(ids)
    cached_already = len(ids) - len(missing(subject, ids))
    if max_calls is not None:
        todo = todo[:max_calls]
    print(f"\n{subject.upper()} TRANSFERS — {len(todo):,} to fetch "
          f"({cached_already:,}/{len(ids):,} already cached)")
    if not todo:
        return Counter()

    outcomes, moves = Counter(), 0
    # Report ~50 times per subject regardless of size. A tens-of-thousands-long
    # player pass with a fixed stride either floods the terminal or goes quiet
    # for minutes; quiet reads as a hang, and this runner is meant to be left
    # unattended.
    stride = max(1, min(200, len(todo) // 50))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(fetch_one, client, subject, i, stop, refresh)
                   for i in todo]
        for done, future in enumerate(as_completed(futures), 1):
            count, outcome = future.result()
            outcomes[outcome] += 1
            if count:
                moves += count
            if done % stride == 0 or done == len(todo):
                # `done` counts skipped-after-stop futures too, so progress
                # against the dataset must use what was actually fetched.
                fetched = done - outcomes["skipped"]
                pct = 100 * (cached_already + fetched) / max(1, len(ids))
                print(f"\r  {fetched:,}/{len(todo):,} this run "
                      f"({outcomes['skipped']:,} skipped after stop) · "
                      f"{pct:.1f}% of all {subject}s · {moves:,} move rows",
                      end="", flush=True)
    print()
    print(f"  outcomes: {dict(outcomes)}")
    return outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="API-Football career transfers crawl")
    parser.add_argument("--target", default="team",
                        choices=list(SUBJECTS) + ["all"],
                        help="team (~845 calls, run first), player (the long "
                             "tail), or all (default: team)")
    parser.add_argument("--include-discovered", action="store_true",
                        help="add players named ONLY by cached team transfer "
                             "files — players no other endpoint here can see. "
                             "Requires --target team to have run.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch even cached subjects (transfer windows "
                             "move; the cached `update` timestamp says when a "
                             "player was last touched vendor-side)")
    parser.add_argument("--max-calls", type=int,
                        help="cap calls PER SUBJECT this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the outstanding work and cost, make no calls")
    args = parser.parse_args(argv)

    chosen = (list(SUBJECT_ORDER) if args.target == "all" else [args.target])
    chosen = [s for s in SUBJECT_ORDER if s in chosen]

    plans, total = [], 0
    for subject in chosen:
        ids, note = build_work_list(subject, args.include_discovered)
        if not ids:
            print(f"\n! {subject}: {note}")
            return 1
        outstanding = len(ids) if args.refresh else len(missing(subject, ids))
        if args.max_calls is not None:
            outstanding = min(outstanding, args.max_calls)
        plans.append((subject, ids, outstanding))
        total += outstanding
        print(f"\n{subject}: {note}")
        print(f"    {outstanding:,} outstanding "
              f"({len(ids) - len(missing(subject, ids)):,} cached)")

    if args.dry_run:
        print(f"\n  total calls: ~{total:,}  ≈ {total / 75000:.2f} day(s) at "
              f"75,000/day")
        if "player" in chosen and not args.include_discovered:
            print("  Add --include-discovered to also crawl players that only "
                  "the team\n  transfer files name — strictly more coverage "
                  "than /players can reach.")
        print("  Interrupt freely: every fetch is cached and a re-run resumes "
              "from what is missing.")
        report_paging_anomalies()
        return 0

    client = make_client("transfers")
    if client is None:
        return 1
    stop = threading.Event()

    for subject, ids, _outstanding in plans:
        # Recompute the player work list here rather than trusting the one built
        # for the plan above. With `--target all` the team pass runs in THIS
        # loop, so the plan's discovery set was computed before those files
        # existed — using it would quietly crawl only the players a previous
        # run had discovered, and report a complete pass while doing it.
        if subject == "player" and args.include_discovered:
            ids, note = build_work_list("player", True)
            print(f"\nplayer work list re-derived after the team pass: {note}")
        run_subject(client, subject, ids, args.concurrency, stop,
                    args.refresh, args.max_calls)
        if stop.is_set():
            print("\n! daily quota exhausted — stopping. Everything fetched is "
                  "cached;\n  re-run tomorrow to continue from exactly here.")
            break

    report_paging_anomalies()
    if "team" in chosen and not stop.is_set():
        fresh = discovered_player_ids() - set(cached_player_ids()[0])
        if fresh:
            print(f"\n{len(fresh):,} player ids appear in team transfer files "
                  f"and NOWHERE else in this cache.\nCrawl their full careers "
                  f"with:\n  uv run python -m ingest.apifootball.transfers "
                  f"--target player --include-discovered")

    print(f"\nquota: {client.quota()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
