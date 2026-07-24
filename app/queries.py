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


_INJURY_SELECT = """
    SELECT injury.id, injury.player_id, injury.start_date, injury.end_date,
           injury.duration_days, injury.games_missed, injury.is_ongoing,
           injury.age_at_start, injury.fixture_appearances,
           player.name AS player, player.position, team.name AS team,
           league.country, league.name AS league, injury_type.name AS type
    FROM injury
    LEFT JOIN player ON player.id = injury.player_id
    LEFT JOIN team ON team.id = injury.team_id
    LEFT JOIN league ON league.id = injury.league_id
    LEFT JOIN injury_type ON injury_type.id = injury.type_id
"""

_SORTABLE = {"start_date": "injury.start_date", "duration": "injury.duration_days",
             "games_missed": "injury.games_missed", "player": "player.name",
             "league": "league.name"}


def injury_list(connection, country=None, position=None, type_name=None, ongoing_only=False,
                sort="start_date", direction="desc", page=1, per_page=50):
    """Filter and paginate records, with a whitelist for interpolated ordering."""
    conditions, params = [], []
    for value, column in ((country, "league.country"), (position, "player.position"),
                          (type_name, "injury_type.name")):
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    if ongoing_only:
        conditions.append("injury.is_ongoing = 1")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = connection.execute(f"SELECT COUNT(*) FROM ({_INJURY_SELECT} {where})", params).fetchone()[0]
    page = max(page, 1)
    per_page = min(max(per_page, 1), 200)
    column = _SORTABLE.get(sort, _SORTABLE["start_date"])
    order = "ASC" if direction.lower() == "asc" else "DESC"
    items = rows(connection, f"{_INJURY_SELECT} {where} ORDER BY {column} {order}, injury.id DESC LIMIT ? OFFSET ?",
                 (*params, per_page, (page - 1) * per_page))
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def filter_options(connection):
    return {
        "countries": [row["country"] for row in rows(connection, "SELECT DISTINCT country FROM league WHERE country IS NOT NULL ORDER BY country")],
        "positions": [row["position"] for row in rows(connection, "SELECT DISTINCT position FROM player WHERE position IS NOT NULL ORDER BY position")],
        "types": [row["name"] for row in rows(connection, "SELECT DISTINCT injury_type.name FROM injury JOIN injury_type ON injury_type.id = injury.type_id ORDER BY injury_type.name")],
    }


def player_timeline(connection, player_id):
    player = connection.execute("SELECT * FROM player WHERE id = ?", (player_id,)).fetchone()
    injuries = rows(connection, f"{_INJURY_SELECT} WHERE injury.player_id = ? ORDER BY injury.start_date DESC", (player_id,))
    return {"player": dict(player) if player else None, "injuries": injuries}
