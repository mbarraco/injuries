"""All application SQL, kept independent of FastAPI routes for testing."""
from app.db import rows


def overview(connection):
    return dict(connection.execute("""
        SELECT
          (SELECT COUNT(*) FROM injury) AS injuries,
          (SELECT COUNT(DISTINCT league_id) FROM injury) AS leagues,
          (SELECT COUNT(DISTINCT player_id) FROM injury) AS players,
          (SELECT COUNT(DISTINCT team_id) FROM injury) AS teams,
          (SELECT MIN(start_date) FROM injury) AS earliest,
          (SELECT MAX(start_date) FROM injury) AS latest,
          (SELECT COUNT(*) FROM injury WHERE is_ongoing = 1) AS ongoing
    """).fetchone())


def quality_metrics(connection):
    return rows(connection, "SELECT metric, value, detail FROM data_quality ORDER BY metric")


def coverage_by_league(connection):
    return rows(connection, """
        SELECT country, league,
               MAX(CASE WHEN period = 1 THEN record_count END) AS yr1,
               MAX(CASE WHEN period = 2 THEN record_count END) AS yr2,
               MAX(CASE WHEN period = 3 THEN record_count END) AS yr3,
               MAX(CASE WHEN period = 3 THEN tier END) AS tier
        FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY league_id ORDER BY year_bucket) AS period
          FROM league_coverage
        )
        GROUP BY country, league, league_id
        ORDER BY yr3 DESC, league
    """)


def by_position(connection):
    return rows(connection, """
        SELECT COALESCE(player.position, 'Unknown') AS position, COUNT(*) AS injuries,
               ROUND(AVG(injury.duration_days), 1) AS avg_duration,
               ROUND(AVG(injury.games_missed), 1) AS avg_games_missed
        FROM injury LEFT JOIN player ON player.id = injury.player_id
        GROUP BY position ORDER BY injuries DESC, position
    """)


def by_age_band(connection):
    return rows(connection, """
        SELECT CASE WHEN age_at_start IS NULL THEN 'Unknown'
                    WHEN age_at_start < 20 THEN 'Under 20'
                    WHEN age_at_start < 25 THEN '20-24'
                    WHEN age_at_start < 30 THEN '25-29'
                    WHEN age_at_start < 35 THEN '30-34'
                    ELSE '35+' END AS band,
               COUNT(*) AS injuries, ROUND(AVG(duration_days), 1) AS avg_duration
        FROM injury GROUP BY band
        ORDER BY CASE band WHEN 'Under 20' THEN 1 WHEN '20-24' THEN 2
                           WHEN '25-29' THEN 3 WHEN '30-34' THEN 4
                           WHEN '35+' THEN 5 ELSE 6 END
    """)


def by_type(connection, limit=15):
    return rows(connection, """
        SELECT COALESCE(injury_type.name, 'Unknown') AS type, COUNT(*) AS injuries,
               ROUND(AVG(injury.duration_days), 1) AS avg_duration,
               ROUND(AVG(injury.games_missed), 1) AS avg_games_missed
        FROM injury LEFT JOIN injury_type ON injury_type.id = injury.type_id
        GROUP BY type ORDER BY injuries DESC, type LIMIT ?
    """, (limit,))


def by_nationality(connection, limit=15):
    return rows(connection, """
        SELECT COALESCE(player.nationality, 'Unknown') AS nationality, COUNT(*) AS injuries
        FROM injury LEFT JOIN player ON player.id = injury.player_id
        GROUP BY nationality ORDER BY injuries DESC, nationality LIMIT ?
    """, (limit,))


def by_league(connection):
    return rows(connection, """
        SELECT COALESCE(league.country, 'Unknown') AS country,
               COALESCE(league.name, 'Unknown') AS league, COUNT(*) AS injuries,
               ROUND(AVG(injury.duration_days), 1) AS avg_duration
        FROM injury LEFT JOIN league ON league.id = injury.league_id
        GROUP BY country, league ORDER BY injuries DESC, league
    """)


def by_month(connection):
    return rows(connection, """
        SELECT strftime('%m', start_date) AS month, COUNT(*) AS injuries
        FROM injury WHERE start_date IS NOT NULL GROUP BY month ORDER BY month
    """)


# One projection, two sources: the `injury` view (category-filtered) or the
# full `absence` table. Parameterised via {source} rather than str.replace() on
# the finished SQL — replace() rewrites *every* match, so any later subquery or
# CTE containing the same substring would be silently corrupted.
#
# The source is always a literal from this module, never user input; it is
# interpolated because a table name cannot be a bound parameter.
_ABSENCE_PROJECTION = """
    SELECT injury.id, injury.category, injury.player_id, injury.start_date, injury.end_date,
           injury.duration_days, injury.games_missed, injury.is_ongoing,
           injury.age_at_start, injury.fixture_appearances,
           player.name AS player, player.position,
           team.id AS team_id, team.name AS team,
           league.id AS league_id, league.country, league.name AS league,
           injury_type.id AS type_id, injury_type.name AS type
    FROM {source} AS injury
    LEFT JOIN player ON player.id = injury.player_id
    LEFT JOIN team ON team.id = injury.team_id
    LEFT JOIN league ON league.id = injury.league_id
    LEFT JOIN injury_type ON injury_type.id = injury.type_id
"""

_INJURY_SELECT = _ABSENCE_PROJECTION.format(source="injury")
_ABSENCE_SELECT = _ABSENCE_PROJECTION.format(source="absence")

_SORTABLE = {"start_date": "injury.start_date", "duration": "injury.duration_days",
             "games_missed": "injury.games_missed", "player": "player.name",
             "league": "league.name"}


def injury_list(connection, category="injury", country=None, position=None, type_name=None, ongoing_only=False,
                sort="start_date", direction="desc", page=1, per_page=50):
    """Filter and paginate absence records, with a whitelist for interpolated ordering.

    `category`: "injury" (default — identical to this function's original,
    injury-only behaviour, so every existing caller is unaffected), a specific
    category value such as "suspended", or None for every category.
    """
    conditions, params = [], []
    if category == "injury":
        select = _INJURY_SELECT
    else:
        select = _ABSENCE_SELECT
        if category is not None:
            conditions.append("injury.category = ?")
            params.append(category)
    for value, column in ((country, "league.country"), (position, "player.position"),
                          (type_name, "injury_type.name")):
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    if ongoing_only:
        conditions.append("injury.is_ongoing = 1")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = connection.execute(f"SELECT COUNT(*) FROM ({select} {where})", params).fetchone()[0]
    page = max(page, 1)
    per_page = min(max(per_page, 1), 200)
    column = _SORTABLE.get(sort, _SORTABLE["start_date"])
    order = "ASC" if direction.lower() == "asc" else "DESC"
    items = rows(connection, f"{select} {where} ORDER BY {column} {order}, injury.id DESC LIMIT ? OFFSET ?",
                 (*params, per_page, (page - 1) * per_page))
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def filter_options(connection):
    return {
        "countries": [row["country"] for row in rows(connection, "SELECT DISTINCT country FROM league WHERE country IS NOT NULL ORDER BY country")],
        "positions": [row["position"] for row in rows(connection, "SELECT DISTINCT position FROM player WHERE position IS NOT NULL ORDER BY position")],
        "types": [row["name"] for row in rows(connection, "SELECT DISTINCT injury_type.name FROM injury JOIN injury_type ON injury_type.id = injury.type_id ORDER BY injury_type.name")],
    }


def player_timeline(connection, player_id):
    """A player plus everything reachable from it: injuries, season minutes,
    transfer history, and the current team derived from the current season."""
    player = connection.execute("SELECT * FROM player WHERE id = ?", (player_id,)).fetchone()
    injuries = rows(connection, f"{_INJURY_SELECT} WHERE injury.player_id = ? ORDER BY injury.start_date DESC", (player_id,))
    seasons = rows(connection, """
        SELECT player_season.season_id, season.name AS season_name, season.is_current,
               player_season.team_id, team.name AS team_name,
               player_season.minutes_played, player_season.appearances
        FROM player_season
        JOIN season ON season.id = player_season.season_id
        LEFT JOIN team ON team.id = player_season.team_id
        WHERE player_season.player_id = ?
        ORDER BY season.name DESC
    """, (player_id,))
    transfers = rows(connection, """
        SELECT transfer.id, transfer.date,
               transfer.from_team_id, from_team.name AS from_team,
               transfer.to_team_id, to_team.name AS to_team
        FROM transfer
        LEFT JOIN team AS from_team ON from_team.id = transfer.from_team_id
        LEFT JOIN team AS to_team ON to_team.id = transfer.to_team_id
        WHERE transfer.player_id = ? ORDER BY transfer.date DESC
    """, (player_id,))
    current = next((season for season in seasons if season["is_current"]), None)
    current_team = ({"id": current["team_id"], "name": current["team_name"]}
                    if current and current["team_id"] else None)
    return {"player": dict(player) if player else None, "injuries": injuries,
            "seasons": seasons, "transfers": transfers, "current_team": current_team}


def leagues_index(connection):
    return rows(connection, """
        SELECT league.id, league.country, league.name,
               COUNT(DISTINCT absence.team_id) AS teams,
               COUNT(absence.id) AS absences
        FROM league LEFT JOIN absence ON absence.league_id = league.id
        GROUP BY league.id, league.country, league.name
        ORDER BY league.country, league.name
    """)


def league_detail(connection, league_id):
    """A league plus everything reachable from it."""
    league = connection.execute("SELECT * FROM league WHERE id = ?", (league_id,)).fetchone()
    if league is None:
        return None
    return {
        "league": dict(league),
        "teams": rows(connection, """
            SELECT team.id, team.name, COUNT(absence.id) AS absences
            FROM absence
            JOIN team ON team.id = absence.team_id
            WHERE absence.league_id = ?
            GROUP BY team.id, team.name ORDER BY absences DESC
        """, (league_id,)),
        "seasons": rows(connection, """
            SELECT id, name, is_current FROM season
            WHERE league_id = ? ORDER BY name DESC
        """, (league_id,)),
        "types": rows(connection, """
            SELECT injury_type.id, injury_type.name AS type, COUNT(*) AS n,
                   ROUND(AVG(absence.duration_days), 1) AS avg_days
            FROM absence LEFT JOIN injury_type ON injury_type.id = absence.type_id
            WHERE absence.league_id = ? AND absence.category = 'injury'
            GROUP BY injury_type.id, type ORDER BY n DESC LIMIT 10
        """, (league_id,)),
    }


def teams_index(connection):
    return rows(connection, """
        SELECT team.id, team.name, team.country, COUNT(absence.id) AS absences
        FROM team LEFT JOIN absence ON absence.team_id = team.id
        GROUP BY team.id, team.name, team.country
        ORDER BY absences DESC, team.name
    """)


# Row caps for the detail pages. Named so the templates can report "N of M"
# rather than presenting a capped list as a complete one.
ABSENCE_LIMIT = 50
TRANSFER_LIMIT = 20
PLAYER_LIMIT = 50


def _count(connection, sql, *params):
    return connection.execute(sql, params).fetchone()[0]


def team_detail(connection, team_id):
    """A team plus everything reachable from it."""
    team = connection.execute("SELECT * FROM team WHERE id = ?", (team_id,)).fetchone()
    if team is None:
        return None
    return {
        "team": dict(team),
        "leagues": rows(connection, """
            SELECT DISTINCT league.id, league.name
            FROM absence JOIN league ON league.id = absence.league_id
            WHERE absence.team_id = ?
        """, (team_id,)),
        "squad": rows(connection, """
            SELECT player.id, player.name, player.position,
                   player_season.season_id, season.name AS season_name,
                   player_season.minutes_played
            FROM player_season
            JOIN player ON player.id = player_season.player_id
            JOIN season ON season.id = player_season.season_id
            WHERE player_season.team_id = ? AND season.is_current = 1
            ORDER BY player.name
        """, (team_id,)),
        # category='injury' to match league_detail and type_detail, which
        # already filtered this way — previously team pages listed every
        # category while those two didn't, an inconsistency rather than a
        # decision. All three now filter identically and explicitly.
        "absences": rows(connection, f"""
            {_INJURY_SELECT}
            WHERE injury.team_id = ? ORDER BY injury.start_date DESC LIMIT ?
        """, (team_id, ABSENCE_LIMIT)),
        # Totals accompany every capped list: a truncated table is fine, but a
        # heading that reports the page size as if it were the total is not.
        # Team 88 holds 290 absences and would otherwise display "(50)".
        "absences_total": _count(
            connection, "SELECT COUNT(*) FROM absence WHERE team_id = ? AND category = 'injury'", team_id),
        "absences_limit": ABSENCE_LIMIT,
        "transfers_in": rows(connection, """
            SELECT transfer.id, transfer.date, player.id AS player_id, player.name AS player,
                   transfer.from_team_id, from_team.name AS from_team
            FROM transfer
            JOIN player ON player.id = transfer.player_id
            LEFT JOIN team AS from_team ON from_team.id = transfer.from_team_id
            WHERE transfer.to_team_id = ? ORDER BY transfer.date DESC LIMIT ?
        """, (team_id, TRANSFER_LIMIT)),
        "transfers_in_total": _count(
            connection, "SELECT COUNT(*) FROM transfer WHERE to_team_id = ?", team_id),
        "transfers_out": rows(connection, """
            SELECT transfer.id, transfer.date, player.id AS player_id, player.name AS player,
                   transfer.to_team_id, to_team.name AS to_team
            FROM transfer
            JOIN player ON player.id = transfer.player_id
            LEFT JOIN team AS to_team ON to_team.id = transfer.to_team_id
            WHERE transfer.from_team_id = ? ORDER BY transfer.date DESC LIMIT ?
        """, (team_id, TRANSFER_LIMIT)),
        "transfers_out_total": _count(
            connection, "SELECT COUNT(*) FROM transfer WHERE from_team_id = ?", team_id),
        "transfer_limit": TRANSFER_LIMIT,
    }


def seasons_index(connection):
    return rows(connection, """
        SELECT season.id, season.name, season.is_current,
               league.id AS league_id, league.name AS league_name,
               COUNT(absence.id) AS absences
        FROM season
        JOIN league ON league.id = season.league_id
        LEFT JOIN absence ON absence.season_id = season.id AND absence.category = 'injury'
        GROUP BY season.id, season.name, season.is_current, league.id, league.name
        ORDER BY league.name, season.name DESC
    """)


def season_detail(connection, season_id):
    """A season plus everything reachable from it."""
    season = connection.execute("""
        SELECT season.id, season.name, season.is_current,
               league.id AS league_id, league.name AS league_name
        FROM season JOIN league ON league.id = season.league_id
        WHERE season.id = ?
    """, (season_id,)).fetchone()
    if season is None:
        return None
    return {
        "season": dict(season),
        "absences": rows(connection, f"""
            {_INJURY_SELECT}
            WHERE injury.season_id = ? ORDER BY injury.start_date DESC LIMIT ?
        """, (season_id, ABSENCE_LIMIT)),
        "absences_total": _count(
            connection, "SELECT COUNT(*) FROM absence WHERE season_id = ? AND category = 'injury'", season_id),
        "absences_limit": ABSENCE_LIMIT,
        "players": rows(connection, """
            SELECT player.id, player.name, player_season.team_id,
                   team.name AS team_name, player_season.minutes_played
            FROM player_season
            JOIN player ON player.id = player_season.player_id
            LEFT JOIN team ON team.id = player_season.team_id
            WHERE player_season.season_id = ?
            ORDER BY player_season.minutes_played DESC
            LIMIT ?
        """, (season_id, PLAYER_LIMIT)),
        "players_total": _count(
            connection, "SELECT COUNT(*) FROM player_season WHERE season_id = ?", season_id),
        "player_limit": PLAYER_LIMIT,
    }


def types_index(connection):
    return rows(connection, """
        SELECT injury_type.id, injury_type.name, COUNT(*) AS injuries,
               ROUND(AVG(absence.duration_days), 1) AS avg_duration
        FROM absence JOIN injury_type ON injury_type.id = absence.type_id
        WHERE absence.category = 'injury'
        GROUP BY injury_type.id, injury_type.name
        ORDER BY injuries DESC
    """)


def search(connection, query, per_kind=8):
    """Prefix search across players, teams and leagues, for the global search box.

    Prefix (`q%`) rather than substring (`%q%`) so SQLite can use the name
    indexes/primary sort order instead of scanning every row. Queries under 2
    characters return [] — a 1-char prefix matches thousands of rows and is
    never a useful result set.
    """
    if not query or len(query.strip()) < 2:
        return []
    like = f"{query.strip()}%"
    results = []
    for kind, sql in (
        ("player", "SELECT id, name FROM player WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
        ("team",   "SELECT id, name FROM team   WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
        ("league", "SELECT id, name FROM league WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?"),
    ):
        results.extend({**row, "kind": kind} for row in rows(connection, sql, (like, per_kind)))
    return results


def type_detail(connection, type_id):
    """An injury type plus everything reachable from it."""
    injury_type = connection.execute("SELECT * FROM injury_type WHERE id = ?", (type_id,)).fetchone()
    if injury_type is None:
        return None
    return {
        "type": dict(injury_type),
        "players": rows(connection, """
            SELECT player.id, player.name, COUNT(*) AS occurrences,
                   ROUND(AVG(absence.duration_days), 1) AS avg_days
            FROM absence JOIN player ON player.id = absence.player_id
            WHERE absence.type_id = ? AND absence.category = 'injury'
            GROUP BY player.id, player.name ORDER BY occurrences DESC LIMIT ?
        """, (type_id, PLAYER_LIMIT)),
        "players_total": _count(
            connection,
            "SELECT COUNT(DISTINCT player_id) FROM absence WHERE type_id = ? AND category = 'injury'",
            type_id),
        "player_limit": PLAYER_LIMIT,
        "positions": rows(connection, """
            SELECT COALESCE(player.position, 'Unknown') AS position, COUNT(*) AS injuries
            FROM absence LEFT JOIN player ON player.id = absence.player_id
            WHERE absence.type_id = ? AND absence.category = 'injury'
            GROUP BY position ORDER BY injuries DESC
        """, (type_id,)),
        "summary": dict(connection.execute("""
            SELECT COUNT(*) AS injuries, ROUND(AVG(duration_days), 1) AS avg_duration,
                   ROUND(AVG(games_missed), 1) AS avg_games_missed
            FROM absence WHERE type_id = ? AND category = 'injury'
        """, (type_id,)).fetchone()),
    }
