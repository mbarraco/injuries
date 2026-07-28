"""Cross-tabulations of what the dataset holds, by season.

Deliberately NOT a generic cross-tab engine: each measure declares complete
SQL per row dimension rather than assembling one from parts — easier to read
and test for four measures across up to three scopes than a whitelisted,
interpolated version would be.

Two attribution gaps shape this module, both surfaced rather than hidden:

- `fixture_coverage` carries only (league_id, season_id) — fixtures aren't
  tied to a club or player, so the `fixtures` measure has no club/player
  scope at all (see Measure.by_club/by_player, left None).
- `transfer` carries a date and team ids but no league_id or season_id. A
  raw date-range join against `season` would match every league running the
  same Aug-May calendar for the same date, so transfers are instead matched
  through the *destination* team's own season windows (via player_season,
  the closest thing to a roster this schema has) — see the `roster` subquery
  in the transfer SQL below. A transfer whose team/date combination matches
  no window at all cannot be placed in any row and is reported as
  `unmatched_transfers`, league-scope only: club/player transfer grids show
  matched transfers only, since narrowing an already-unmatched transfer to a
  specific club or player is not well-defined either.
"""
from dataclasses import dataclass

from app.db import rows

_ROW_LABELS = {"league": "League", "club": "Club", "player": "Player"}

_ABSENCES_LEAGUE = """
    SELECT league.id AS row_id, league.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM absence
    JOIN league ON league.id = absence.league_id
    LEFT JOIN season ON season.id = absence.season_id
    GROUP BY league.id, league.name, season.name, season.starting_at
"""
_ABSENCES_CLUB = """
    SELECT team.id AS row_id, team.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM absence
    JOIN team ON team.id = absence.team_id
    LEFT JOIN season ON season.id = absence.season_id
    WHERE absence.league_id = ?
    GROUP BY team.id, team.name, season.name, season.starting_at
"""
_ABSENCES_PLAYER = """
    SELECT player.id AS row_id, player.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM absence
    JOIN player ON player.id = absence.player_id
    LEFT JOIN season ON season.id = absence.season_id
    WHERE absence.team_id = ?
    GROUP BY player.id, player.name, season.name, season.starting_at
"""

# Minutes has no per-row unattributed path: a player_season row's league is
# DERIVED from its season (there is no minutes.league_id to fall back on), so
# an unresolvable season_id leaves it with no row to attach to at all —
# handled the same way as transfers' unmatched, not as a per-row column.
_MINUTES_LEAGUE = """
    SELECT league.id AS row_id, league.name AS row_label, season.name AS season,
           season.starting_at AS season_start, SUM(player_season.minutes_played) AS value
    FROM player_season
    JOIN season ON season.id = player_season.season_id
    JOIN league ON league.id = season.league_id
    GROUP BY league.id, league.name, season.name, season.starting_at
"""
_MINUTES_CLUB = """
    SELECT team.id AS row_id, team.name AS row_label, season.name AS season,
           season.starting_at AS season_start, SUM(player_season.minutes_played) AS value
    FROM player_season
    JOIN season ON season.id = player_season.season_id
    JOIN team ON team.id = player_season.team_id
    WHERE season.league_id = ?
    GROUP BY team.id, team.name, season.name, season.starting_at
"""
_MINUTES_PLAYER = """
    SELECT player.id AS row_id, player.name AS row_label, season.name AS season,
           season.starting_at AS season_start, SUM(player_season.minutes_played) AS value
    FROM player_season
    JOIN season ON season.id = player_season.season_id
    JOIN player ON player.id = player_season.player_id
    WHERE player_season.team_id = ?
    GROUP BY player.id, player.name, season.name, season.starting_at
"""

_FIXTURES_LEAGUE = """
    SELECT league.id AS row_id, league.name AS row_label, season.name AS season,
           season.starting_at AS season_start, SUM(fixture_coverage.fixtures) AS value
    FROM fixture_coverage
    JOIN league ON league.id = fixture_coverage.league_id
    LEFT JOIN season ON season.id = fixture_coverage.season_id
    GROUP BY league.id, league.name, season.name, season.starting_at
"""

# `roster` is every (team_id, season_id) pair that ever fielded a player,
# from player_season — the closest thing to squad membership this schema
# has. A transfer is attributed to whichever of the destination team's
# seasons has a window containing the transfer date.
_TRANSFER_ROSTER = "(SELECT DISTINCT team_id, season_id FROM player_season)"
_TRANSFERS_LEAGUE = f"""
    SELECT league.id AS row_id, league.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM transfer
    JOIN {_TRANSFER_ROSTER} AS roster ON roster.team_id = transfer.to_team_id
    JOIN season ON season.id = roster.season_id
     AND transfer.date BETWEEN season.starting_at AND season.ending_at
    JOIN league ON league.id = season.league_id
    GROUP BY league.id, league.name, season.name, season.starting_at
"""
_TRANSFERS_CLUB = f"""
    SELECT team.id AS row_id, team.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM transfer
    JOIN team ON team.id = transfer.to_team_id
    JOIN {_TRANSFER_ROSTER} AS roster ON roster.team_id = transfer.to_team_id
    JOIN season ON season.id = roster.season_id
     AND transfer.date BETWEEN season.starting_at AND season.ending_at
    WHERE season.league_id = ?
    GROUP BY team.id, team.name, season.name, season.starting_at
"""
_TRANSFERS_PLAYER = f"""
    SELECT player.id AS row_id, player.name AS row_label, season.name AS season,
           season.starting_at AS season_start, COUNT(*) AS value
    FROM transfer
    JOIN player ON player.id = transfer.player_id
    JOIN {_TRANSFER_ROSTER} AS roster ON roster.team_id = transfer.to_team_id
    JOIN season ON season.id = roster.season_id
     AND transfer.date BETWEEN season.starting_at AND season.ending_at
    WHERE transfer.to_team_id = ?
    GROUP BY player.id, player.name, season.name, season.starting_at
"""

_UNMATCHED_TRANSFERS = f"""
    SELECT COUNT(*) AS n FROM transfer
    WHERE NOT EXISTS (
        SELECT 1 FROM {_TRANSFER_ROSTER} AS roster
        JOIN season ON season.id = roster.season_id
         AND transfer.date BETWEEN season.starting_at AND season.ending_at
        WHERE roster.team_id = transfer.to_team_id
    )
"""
_UNMATCHED_PLAYER_SEASONS = """
    SELECT COUNT(*) AS n FROM player_season WHERE season_id NOT IN (SELECT id FROM season)
"""


@dataclass(frozen=True)
class Measure:
    label: str
    by_league: str
    by_club: str | None = None
    by_player: str | None = None

    def sql_for(self, scope):
        return {"league": self.by_league, "club": self.by_club, "player": self.by_player}[scope]

    def supports(self, scope):
        return self.sql_for(scope) is not None


MEASURES = {
    "absences": Measure(label="Absences", by_league=_ABSENCES_LEAGUE,
                        by_club=_ABSENCES_CLUB, by_player=_ABSENCES_PLAYER),
    "transfers": Measure(label="Transfers", by_league=_TRANSFERS_LEAGUE,
                         by_club=_TRANSFERS_CLUB, by_player=_TRANSFERS_PLAYER),
    "minutes": Measure(label="Minutes played", by_league=_MINUTES_LEAGUE,
                       by_club=_MINUTES_CLUB, by_player=_MINUTES_PLAYER),
    "fixtures": Measure(label="Fixtures", by_league=_FIXTURES_LEAGUE),
}


def build(connection, measure, scope="league", scope_id=None):
    """Pivot one measure into {seasons, rows, unattributed, max}.

    Pivoting happens here, not in SQL: the season axis grows as more cup
    history is cached, and a SQL pivot would hardcode the columns.

    Empty and zero are different claims (a coverage view's whole point), so
    a season absent from a row's `cells` means "we hold nothing", while a
    present `0` means "we hold data and it recorded no events". At league
    scope every league is scaffolded in up front from the `league` table
    (a real, independent dimension) so a competition with zero data for this
    measure still renders as a blank row rather than vanishing; club/player
    scope has no equivalent independent membership source in this schema; a
    club with no records for a measure does not appear at all.
    """
    spec = MEASURES[measure]
    sql = spec.sql_for(scope)
    if sql is None:
        raise ValueError(f"{measure!r} has no {scope!r} scope")
    params = () if scope == "league" else (scope_id,)

    row_order, row_by_id = [], {}
    if scope == "league":
        for entry in rows(connection, "SELECT id, name FROM league ORDER BY name"):
            row_by_id[entry["id"]] = {"id": entry["id"], "label": entry["name"],
                                      "cells": {}, "total": 0, "unattributed": 0}
            row_order.append(entry["id"])

    season_start = {}
    for record in rows(connection, sql, params):
        row_id = record["row_id"]
        row = row_by_id.get(row_id)
        if row is None:
            row = {"id": row_id, "label": record["row_label"], "cells": {}, "total": 0, "unattributed": 0}
            row_by_id[row_id] = row
            row_order.append(row_id)
        value = record["value"] or 0
        season = record["season"]
        if season is None:
            row["unattributed"] += value
            continue
        row["cells"][season] = row["cells"].get(season, 0) + value
        row["total"] += value
        start = record["season_start"]
        if season not in season_start or (start and (season_start[season] is None or start < season_start[season])):
            season_start[season] = start

    seasons = sorted(season_start, key=lambda name: (season_start[name] is None, season_start[name] or "", name))
    result_rows = ([row_by_id[row_id] for row_id in row_order] if scope == "league"
                   else sorted(row_by_id.values(), key=lambda row: row["label"] or ""))
    max_value = max((v for row in result_rows for v in row["cells"].values()), default=0)

    unmatched = 0
    if scope == "league":
        if measure == "transfers":
            unmatched = rows(connection, _UNMATCHED_TRANSFERS)[0]["n"]
        elif measure == "minutes":
            unmatched = rows(connection, _UNMATCHED_PLAYER_SEASONS)[0]["n"]

    return {
        "measure": measure, "scope": scope, "row_label": _ROW_LABELS[scope],
        "seasons": seasons, "rows": result_rows,
        "unattributed": sum(row["unattributed"] for row in result_rows) + unmatched,
        "unmatched": unmatched, "max": max_value,
    }
