"""Probe `/transfers` before committing quota to it.

`docs/football-api/transfers-endpoint.md` describes what the endpoint *should*
produce. Nothing in this repo has ever called it, so every statement in that
document is unverified. This script answers the six questions that decide
whether a transfer crawl is worth running, and how to shape its schema, for
about 20 calls.

The questions, and why each one changes the plan:

1. **Does `?player={id}` return a full career, or only the window we have
   fixtures for?** The rest of this vendor's data is hard-capped at 2020–2025.
   If transfers reach further back, they are the only endpoint that escapes
   that cap — which would make them disproportionately valuable, because it is
   career history we cannot get any other way.

2. **Does `?team={id}` work, and at what grain?** 845 teams versus 33,750
   players is a 40x cost difference. If the team form returns every move in and
   out of a club, most of the graph is reachable for ~845 calls.

3. **What does `type` actually contain?** The doc claims a small vocabulary
   ("Transfer", "Loan", "Free", "N/A"). If it instead carries fee strings like
   "€ 10M", then `type` is a mixed field and the Sportmonks split of
   `type_id` + `amount INTEGER` cannot be mirrored — it has to be parsed, and
   a parsed fee is inferred, not measured.

4. **Is `page` accepted or rejected?** `/injuries` rejects the field outright
   (`"The Page field do not exist."`) while `/players` paginates. There is no
   uniform rule, and guessing wrong either wastes calls or silently truncates.

5. **Are `teams.in` / `teams.out` ids resolvable?** A career spans clubs far
   outside 47 UEFA competitions. Measuring the miss rate now decides whether
   the schema stores names alongside ids (it will have to) and confirms the
   Sportmonks precedent of NOT making them foreign keys.

6. **Is one player's history internally consistent?** Consecutive moves should
   chain: the club you left is the club you were at. Where they don't chain,
   the "club membership between transfers" inference in the doc is unsafe.

Read-only: writes nothing to `data/raw/`, so it cannot pollute the cache with
exploratory shapes.

Usage:
    uv run python scripts/apifootball/af_probe_transfers.py
    uv run python scripts/apifootball/af_probe_transfers.py --players 276,154
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ingest.apifootball import paths  # noqa: E402
from ingest.apifootball.client import OK  # noqa: E402
from ingest.apifootball.injuries import make_client  # noqa: E402

# Three levels up: scripts/apifootball/x.py -> apifootball -> scripts -> root
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AF_DB = os.path.join(BASE, "app", "apifootball.db")

PROBE_PLAYERS = 6
PROBE_TEAMS = 2


# --------------------------------------------------------------------------- #
# Choosing what to probe: from our own database, so ids are real.
# --------------------------------------------------------------------------- #
def pick_subjects(limit_players=PROBE_PLAYERS, limit_teams=PROBE_TEAMS):
    """Players who appear in the most distinct league-seasons, and big clubs.

    Deliberately NOT random. A player who shows up across many league-seasons
    has probably moved, so their history exercises the multi-record path; a
    random pick could easily be a one-club player whose single record tells us
    nothing about chaining, type variety, or unresolvable clubs.
    """
    if not os.path.exists(AF_DB):
        print(f"! {AF_DB} not found — run: uv run python -m app.etl_af")
        return [], []
    connection = sqlite3.connect(f"file:{AF_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        players = connection.execute("""
            SELECT p.id, p.name, COUNT(DISTINCT ps.team_id) AS clubs
            FROM af_player p
            JOIN af_player_season ps ON ps.player_id = p.id
            GROUP BY p.id
            HAVING clubs > 1
            ORDER BY clubs DESC, p.id
            LIMIT ?
        """, (limit_players,)).fetchall()
        teams = connection.execute("""
            SELECT t.id, t.name, COUNT(*) AS seasons
            FROM af_team t
            JOIN af_player_season ps ON ps.team_id = t.id
            GROUP BY t.id ORDER BY seasons DESC LIMIT ?
        """, (limit_teams,)).fetchall()
    finally:
        connection.close()
    return ([(r["id"], r["name"], r["clubs"]) for r in players],
            [(r["id"], r["name"]) for r in teams])


def known_team_ids():
    """Team ids we can render as links. Everything else is plain text."""
    if not os.path.exists(AF_DB):
        return set()
    connection = sqlite3.connect(f"file:{AF_DB}?mode=ro", uri=True)
    try:
        return {row[0] for row in connection.execute("SELECT id FROM af_team")}
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# Flattening: one row per move, whatever the envelope turns out to be.
# --------------------------------------------------------------------------- #
def flatten(response):
    """Response entries -> flat move rows.

    Written defensively on purpose: this is the first time we have seen the
    payload, so an unexpected shape must show up as a missing field in the
    report rather than a traceback that loses the calls already spent.
    """
    moves = []
    for entry in response or []:
        player = (entry or {}).get("player") or {}
        for move in (entry or {}).get("transfers") or []:
            teams = (move or {}).get("teams") or {}
            moves.append({
                "player_id": player.get("id"),
                "player": player.get("name"),
                "update": (entry or {}).get("update"),
                "date": (move or {}).get("date"),
                "type": (move or {}).get("type"),
                "out_id": ((teams.get("out") or {}).get("id")),
                "out_name": ((teams.get("out") or {}).get("name")),
                "in_id": ((teams.get("in") or {}).get("id")),
                "in_name": ((teams.get("in") or {}).get("name")),
            })
    return moves


def report_keys(label, response):
    """Every key actually present, at each level, with a fill count.

    The field inventory is the part that survives: it is what the schema gets
    built from, and it is cheaper to record now than to re-fetch later.
    """
    top, move_keys, team_keys = Counter(), Counter(), Counter()
    for entry in response or []:
        top.update(k for k, v in (entry or {}).items() if v not in (None, "", [], {}))
        for move in (entry or {}).get("transfers") or []:
            move_keys.update(k for k, v in (move or {}).items()
                             if v not in (None, "", [], {}))
            for side in ((move or {}).get("teams") or {}).values():
                team_keys.update(k for k, v in (side or {}).items()
                                 if v not in (None, "", [], {}))
    print(f"  {label} fields:")
    print(f"    entry     {dict(top)}")
    print(f"    transfer  {dict(move_keys)}")
    print(f"    team side {dict(team_keys)}")


# --------------------------------------------------------------------------- #
# The probe.
# --------------------------------------------------------------------------- #
def probe_player(client, player_id, name, resolvable):
    print(f"\n--- /transfers?player={player_id}  ({name})")
    status, body, outcome, detail = client.get("/transfers", {"player": player_id})
    print(f"  status={status} outcome={outcome} results={(body or {}).get('results')}"
          f"{' detail=' + str(detail) if detail else ''}")
    if outcome != OK:
        return []
    response = (body or {}).get("response") or []
    report_keys("player", response)
    moves = flatten(response)
    if not moves:
        print("  ! results>0 but no transfer rows — envelope differs from the doc")
        return []

    dates = sorted(m["date"] for m in moves if m["date"])
    print(f"  {len(moves)} move(s), dates {dates[0] if dates else '?'} .. "
          f"{dates[-1] if dates else '?'}  "
          f"({sum(1 for m in moves if not m['date'])} undated)")
    print(f"  types: {dict(Counter(m['type'] for m in moves))}")

    unknown = {m['out_id'] for m in moves} | {m['in_id'] for m in moves}
    unknown = {i for i in unknown if i is not None} - resolvable
    print(f"  clubs outside af_team: {len(unknown)} of "
          f"{len({i for m in moves for i in (m['out_id'], m['in_id']) if i})}")

    # Chain check: does the club left match the club last joined?
    ordered = sorted((m for m in moves if m["date"]), key=lambda m: m["date"])
    breaks = sum(1 for a, b in zip(ordered, ordered[1:])
                 if a["in_id"] != b["out_id"])
    print(f"  chain breaks: {breaks} of {max(0, len(ordered) - 1)} consecutive pairs")

    for move in ordered[:6]:
        print(f"    {move['date']}  {str(move['type'])[:18]:18} "
              f"{str(move['out_name'])[:22]:22} -> {move['in_name']}")
    if len(ordered) > 6:
        print(f"    … {len(ordered) - 6} more")
    return moves


def probe_team(client, team_id, name, resolvable):
    print(f"\n--- /transfers?team={team_id}  ({name})")
    status, body, outcome, detail = client.get("/transfers", {"team": team_id})
    print(f"  status={status} outcome={outcome} results={(body or {}).get('results')}"
          f"{' detail=' + str(detail) if detail else ''}")
    if outcome != OK:
        return []
    response = (body or {}).get("response") or []
    report_keys("team", response)
    moves = flatten(response)
    dates = sorted(m["date"] for m in moves if m["date"])
    print(f"  {len(response)} player envelope(s), {len(moves)} move rows, "
          f"dates {dates[0] if dates else '?'} .. {dates[-1] if dates else '?'}")

    # The question that decides cost: does ?team return only moves touching
    # this club, or every move in each of those players' careers? If the
    # latter, the team form is a cheap way to harvest whole careers.
    touching = sum(1 for m in moves if team_id in (m["out_id"], m["in_id"]))
    print(f"  moves touching team {team_id}: {touching} of {len(moves)}"
          f"  -> {'club-scoped' if touching == len(moves) else 'FULL CAREERS included'}")
    print(f"  types: {dict(Counter(m['type'] for m in moves))}")
    return moves


def probe_pagination(client, player_id):
    """Does `/transfers` accept `page`, reject it, or ignore it?

    `/injuries` rejects the field with an error; `/players` paginates. Guessing
    wrong is expensive in both directions, so this is worth one call.
    """
    print(f"\n--- pagination: /transfers?player={player_id}&page=2")
    status, body, outcome, detail = client.get(
        "/transfers", {"player": player_id, "page": 2})
    errors = (body or {}).get("errors")
    print(f"  status={status} outcome={outcome} results={(body or {}).get('results')}")
    print(f"  errors={json.dumps(errors) if errors else '{}'}")
    if errors and "page" in json.dumps(errors).lower():
        print("  -> `page` REJECTED, like /injuries. Omit it entirely.")
    else:
        print("  -> `page` accepted or ignored. Compare `results` with page 1 "
              "before trusting get_all here.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Probe API-Football /transfers")
    parser.add_argument("--players", help="comma-separated player ids "
                                         "(default: picked from apifootball.db)")
    parser.add_argument("--teams", help="comma-separated team ids")
    args = parser.parse_args(argv)

    picked_players, picked_teams = pick_subjects()
    if args.players:
        picked_players = [(int(p), "(given)", 0)
                          for p in args.players.split(",") if p.strip()]
    if args.teams:
        picked_teams = [(int(t), "(given)") for t in args.teams.split(",") if t.strip()]
    if not picked_players and not picked_teams:
        return 1

    resolvable = known_team_ids()
    print(f"{len(resolvable):,} team ids resolvable against af_team")
    print(f"probing {len(picked_players)} player(s), {len(picked_teams)} team(s) "
          f"— ~{len(picked_players) + len(picked_teams) + 1} calls")

    client = make_client("probe-transfers")
    if client is None:
        return 1

    all_types, all_moves = Counter(), 0
    for player_id, name, _clubs in picked_players:
        moves = probe_player(client, player_id, name, resolvable)
        all_types.update(m["type"] for m in moves)
        all_moves += len(moves)

    for team_id, name in picked_teams:
        probe_team(client, team_id, name, resolvable)

    if picked_players:
        probe_pagination(client, picked_players[0][0])

    print("\n" + "=" * 70)
    print(f"{all_moves} player-side move rows across {len(picked_players)} players")
    print(f"type vocabulary seen: {dict(all_types)}")
    print("  If any value looks like a fee ('€ 10M', '$ 2.5M'), `type` is a "
          "MIXED field:\n  category and amount share one column and the fee "
          "must be parsed, i.e. inferred.")
    print(f"\nquota: {client.quota()}")
    print(f"\nCost if a full crawl is approved:")
    print(f"  per-player   ~33,750 calls  (af_player rows) — authoritative careers")
    print(f"  per-team          ~845 calls  (af_team rows)  — 40x cheaper, "
          f"coverage depends on the scope answer above")
    print("Nothing was cached. Record the findings in logbook/apifootball.md "
          "before writing a runner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
