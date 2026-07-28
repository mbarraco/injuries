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


def coverage_ramp(connection):
    """The `coverage_<year>` metrics as a series: sidelined rows per fixture, by year.

    This ramp — 0.00 before 2006 to roughly 4 today — is the vendor's backfill
    improving, so it is charted as the caveat behind every year-spanning number
    rather than left as opaque rows in the metrics table.

    Escaped LIKE because `_` is itself a LIKE wildcard: a bare 'coverage_%'
    would also match a future metric called 'coverageXanything'.
    """
    return rows(connection, r"""
        SELECT CAST(SUBSTR(metric, 10) AS INTEGER) AS year,
               value AS per_fixture, detail
        FROM data_quality
        WHERE metric LIKE 'coverage\_%' ESCAPE '\'
        ORDER BY year
    """)


def coverage_totals(connection):
    """Records and span per competition.

    Replaces the Year 1 / Year 2 / Year 3 pivot: that shape encoded a 3-year
    model and cannot describe 62 competitions whose depths differ by design —
    domestic leagues expose exactly 3 seasons, UEFA cups reach back to 2000.
    Depth is reported as the bucket span each competition actually has.
    """
    return rows(connection, """
        SELECT lc.country, lc.league, lc.league_id,
               SUM(lc.record_count) AS records, COUNT(*) AS buckets,
               MIN(lc.year_bucket) AS first_bucket, MAX(lc.year_bucket) AS last_bucket,
               (SELECT tier FROM league_coverage AS latest
                 WHERE latest.league_id = lc.league_id
                 ORDER BY latest.year_bucket DESC LIMIT 1) AS tier
        FROM league_coverage AS lc
        GROUP BY lc.country, lc.league, lc.league_id
        ORDER BY records DESC, lc.league
    """)


DASHBOARD_TOP = 5


def dashboard(connection, top=DASHBOARD_TOP):
    """Headline totals plus the top rows of every view, for the landing page.

    Dedicated LIMITed statements rather than slicing the index queries: those
    aggregate over all 867 teams and 62 leagues to render a full page, which is
    wasted work when five rows are wanted. Ids travel with every row so the
    dashboard can link into the graph rather than print dead text.
    """
    totals = dict(connection.execute("""
        SELECT (SELECT COUNT(*) FROM absence) AS absences,
               (SELECT COUNT(*) FROM injury) AS injuries,
               (SELECT COUNT(*) FROM injury WHERE is_ongoing = 1) AS ongoing,
               (SELECT COUNT(*) FROM player) AS players,
               (SELECT COUNT(*) FROM team) AS teams,
               (SELECT COUNT(*) FROM league) AS leagues,
               (SELECT COUNT(*) FROM season) AS seasons,
               (SELECT COUNT(*) FROM injury_type) AS types
    """).fetchone())
    return {
        "totals": totals,
        "recent": rows(connection, f"""
            {_INJURY_SELECT} ORDER BY injury.start_date DESC, injury.id DESC LIMIT ?
        """, (top,)),
        "players": rows(connection, """
            SELECT player.id, player.name, COUNT(*) AS injuries,
                   (SELECT SUM(minutes_played) FROM player_season
                     WHERE player_season.player_id = player.id) AS minutes
            FROM injury JOIN player ON player.id = injury.player_id
            GROUP BY player.id, player.name
            ORDER BY injuries DESC, player.name LIMIT ?
        """, (top,)),
        "teams": rows(connection, """
            SELECT team.id, team.name, COUNT(*) AS injuries
            FROM injury JOIN team ON team.id = injury.team_id
            GROUP BY team.id, team.name ORDER BY injuries DESC, team.name LIMIT ?
        """, (top,)),
        "leagues": rows(connection, """
            SELECT league.id, league.name, league.country, COUNT(*) AS injuries
            FROM injury JOIN league ON league.id = injury.league_id
            GROUP BY league.id, league.name, league.country
            ORDER BY injuries DESC, league.name LIMIT ?
        """, (top,)),
        "types": rows(connection, """
            SELECT injury_type.id, injury_type.name, COUNT(*) AS injuries,
                   ROUND(AVG(injury.duration_days), 1) AS avg_days
            FROM injury JOIN injury_type ON injury_type.id = injury.type_id
            GROUP BY injury_type.id, injury_type.name ORDER BY injuries DESC LIMIT ?
        """, (top,)),
        "seasons": rows(connection, """
            SELECT season.id, season.name, season.is_current,
                   league.id AS league_id, league.name AS league_name,
                   COUNT(injury.id) AS injuries
            FROM season
            JOIN league ON league.id = season.league_id
            LEFT JOIN injury ON injury.season_id = season.id
            GROUP BY season.id, season.name, season.is_current, league.id, league.name
            ORDER BY season.is_current DESC, injuries DESC LIMIT ?
        """, (top,)),
    }


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
    """Severity profile per injury type.

    Carries `type_id` so each analytics row can link to its type page, and
    groups by that id rather than the name alone — two types sharing a name
    would otherwise merge into one row that no single page can represent.
    """
    return rows(connection, """
        SELECT injury_type.id AS type_id,
               COALESCE(injury_type.name, 'Unknown') AS type, COUNT(*) AS injuries,
               ROUND(AVG(injury.duration_days), 1) AS avg_duration,
               ROUND(AVG(injury.games_missed), 1) AS avg_games_missed
        FROM injury LEFT JOIN injury_type ON injury_type.id = injury.type_id
        GROUP BY injury_type.id, type ORDER BY injuries DESC, type LIMIT ?
    """, (limit,))


def by_nationality(connection, limit=15):
    return rows(connection, """
        SELECT COALESCE(player.nationality, 'Unknown') AS nationality, COUNT(*) AS injuries
        FROM injury LEFT JOIN player ON player.id = injury.player_id
        GROUP BY nationality ORDER BY injuries DESC, nationality LIMIT ?
    """, (limit,))


def by_league(connection):
    """Injury counts per competition, carrying `league_id` so each row links to
    its league page. Grouped by the id for the same reason as by_type."""
    return rows(connection, """
        SELECT league.id AS league_id,
               COALESCE(league.country, 'Unknown') AS country,
               COALESCE(league.name, 'Unknown') AS league, COUNT(*) AS injuries,
               ROUND(AVG(injury.duration_days), 1) AS avg_duration
        FROM injury LEFT JOIN league ON league.id = injury.league_id
        GROUP BY league.id, country, league ORDER BY injuries DESC, league
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


# 13,315 players is not a page. The index is an entry point ranked by injury
# count; search is how a specific player is reached.
PLAYER_INDEX_LIMIT = 100


def players_index(connection, limit=None):
    """Players ranked by injuries, capped, with the real population alongside.

    `limit` reads the module constant at call time rather than binding it as a
    default, so the cap can be lowered in a test to exercise truncation.
    """
    limit = PLAYER_INDEX_LIMIT if limit is None else limit
    return {
        "players": rows(connection, """
            SELECT player.id, player.name, player.position, player.nationality,
                   COUNT(absence.id) AS injuries,
                   (SELECT SUM(minutes_played) FROM player_season
                     WHERE player_season.player_id = player.id) AS minutes
            FROM player
            LEFT JOIN absence ON absence.player_id = player.id
                             AND absence.category = 'injury'
            GROUP BY player.id, player.name, player.position, player.nationality
            ORDER BY injuries DESC, player.name LIMIT ?
        """, (limit,)),
        "total": _count(connection, "SELECT COUNT(*) FROM player"),
        "limit": limit,
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


# ~5 full matches. Below this the denominator is too small for a rate to carry
# meaning: one injury on 90 minutes reads as 11.11 per 1000, twenty times an
# ever-present starter, and would top every ranking while describing nothing.
# Named rather than inlined so one floor governs every ranking and every
# footnote that explains an exclusion.
MINUTES_FLOOR = 450
RATE_LIMIT = 50

# Candidate denominators at (player, season) grain: minutes SUMMED across a
# player's clubs. This aggregation happens BEFORE anything joins to it — that
# ordering is the whole trick. player_season is keyed
# (player_id, season_id, team_id), so a player who moved mid-season holds one
# row per club; joining `absence` onto the raw table multiplies his injuries
# across those rows while each denominator is only one club's minutes. The
# result is inflated and no error is raised.
_SEASON_MINUTES = """
    SELECT player_id, SUM(minutes_played) AS minutes_played, COUNT(*) AS team_rows
    FROM player_season
    WHERE season_id = ? AND minutes_played IS NOT NULL
    GROUP BY player_id
"""

# Candidate denominators at (player, season, team) grain, for a team page:
# minutes at THIS club only, in the club's current season.
_TEAM_MINUTES = """
    SELECT player_season.player_id AS player_id,
           player_season.season_id AS season_id,
           player_season.minutes_played AS minutes_played,
           season.name AS season_name
    FROM player_season
    JOIN season ON season.id = player_season.season_id
    WHERE player_season.team_id = ? AND season.is_current = 1
      AND player_season.minutes_played IS NOT NULL
"""


def _floor_counts(connection, minutes_sql, params):
    """How many candidates sit each side of MINUTES_FLOOR.

    Counted rather than inferred from the returned rows: the ranking is capped
    at `limit`, so its length is a page size, not a population — and the count
    below the floor is what lets a page footnote the exclusion instead of
    performing it silently.
    """
    row = connection.execute(f"""
        SELECT SUM(CASE WHEN minutes_played >= ? THEN 1 ELSE 0 END) AS qualified,
               SUM(CASE WHEN minutes_played <  ? THEN 1 ELSE 0 END) AS below
        FROM ({minutes_sql})
    """, (MINUTES_FLOOR, MINUTES_FLOOR, *params)).fetchone()
    return row["qualified"] or 0, row["below"] or 0


def player_rates(connection, season_id, limit=RATE_LIMIT):
    """Injuries per 1000 minutes for ONE season, at (player, season) grain.

    Minutes come from `_SEASON_MINUTES` (summed per player) and injuries from a
    separate aggregate keyed the same way, so neither side can multiply the
    other — see the comment on `_SEASON_MINUTES` for the join that goes wrong.

    `season_id` is required, not optional: the `coverage_<year>` ramp (0.00
    sidelined-per-fixture pre-2006 to ~4 today) means a rate compared across
    seasons measures the vendor's backfill, not injury risk. There is
    deliberately no all-seasons mode.

    Returns the ranking (players at or above the floor) together with
    `below_floor`, the number the floor removed, so the exclusion is reportable.
    """
    players = rows(connection, f"""
        WITH minutes AS ({_SEASON_MINUTES}),
             injuries AS (
                 SELECT player_id, COUNT(*) AS injuries
                 FROM absence
                 WHERE season_id = ? AND category = 'injury'
                 GROUP BY player_id
             )
        SELECT player.id, player.name, player.position,
               minutes.minutes_played, minutes.team_rows,
               COALESCE(injuries.injuries, 0) AS injuries,
               ROUND(COALESCE(injuries.injuries, 0) * 1000.0 / minutes.minutes_played, 2)
                 AS rate_per_1000
        FROM minutes
        JOIN player ON player.id = minutes.player_id
        LEFT JOIN injuries ON injuries.player_id = minutes.player_id
        WHERE minutes.minutes_played >= ?
        ORDER BY rate_per_1000 DESC, minutes.minutes_played DESC
        LIMIT ?
    """, (season_id, season_id, MINUTES_FLOOR, limit))
    qualified, below = _floor_counts(connection, _SEASON_MINUTES, (season_id,))
    return {"players": players, "total": qualified, "below_floor": below,
            "minutes_floor": MINUTES_FLOOR, "limit": limit}


def team_rates(connection, team_id, limit=RATE_LIMIT):
    """Injuries per 1000 minutes for a team's current-season squad.

    Grain is (player, season, team) here, not (player, season): on a team page
    the question is how a player fared *at this club*, so both sides are scoped
    to it — minutes from the club's `player_season` row, injuries from absences
    recorded against the club. A player who arrived mid-season shows only his
    minutes and injuries here; the season page reports his whole season.
    """
    players = rows(connection, f"""
        WITH minutes AS ({_TEAM_MINUTES}),
             injuries AS (
                 SELECT player_id, season_id, COUNT(*) AS injuries
                 FROM absence
                 WHERE team_id = ? AND category = 'injury'
                 GROUP BY player_id, season_id
             )
        SELECT player.id, player.name, player.position,
               minutes.season_id, minutes.season_name, minutes.minutes_played,
               COALESCE(injuries.injuries, 0) AS injuries,
               ROUND(COALESCE(injuries.injuries, 0) * 1000.0 / minutes.minutes_played, 2)
                 AS rate_per_1000
        FROM minutes
        JOIN player ON player.id = minutes.player_id
        LEFT JOIN injuries ON injuries.player_id = minutes.player_id
                          AND injuries.season_id = minutes.season_id
        WHERE minutes.minutes_played >= ?
        ORDER BY rate_per_1000 DESC, minutes.minutes_played DESC
        LIMIT ?
    """, (team_id, team_id, MINUTES_FLOOR, limit))
    qualified, below = _floor_counts(connection, _TEAM_MINUTES, (team_id,))
    return {"players": players, "total": qualified, "below_floor": below,
            "minutes_floor": MINUTES_FLOOR, "limit": limit}


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
        "rates": team_rates(connection, team_id),
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
        "rates": player_rates(connection, season_id),
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
