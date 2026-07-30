"""API-Football query layer, kept independent of FastAPI routes for testing.

Mirrors the shape of `app/queries.py` (dashboard, index/detail pairs, a
filterable list, analytics breakdowns) but the SQL is NOT a copy — see
`app/schema_af.sql` for why the two vendors diverge structurally.

Two things every query here must respect, because getting them wrong produces
plausible wrong numbers rather than an error (see `logbook/apifootball.md`):

1. **`type` distinguishes a confirmed absence from a doubt.** `af_confirmed_absence`
   (type = 'Missing Fixture') is the default population for counts and lists;
   `Questionable` rows are never silently included in a "how many absences" figure.
2. **Rows are (player, fixture) appearances, not spells.** A player out for 8
   matches is 8 rows. Counting af_absence rows as "injuries" overstates real
   injury incidents; anywhere that distinction matters, it is stated in the
   returned dict rather than left for the template to get wrong.
"""
from app.db import rows

# ---- Reason-classification note surfaced wherever a "category" appears ---- #
GRAIN_NOTE = ("Each row is one player missing one fixture. A single injury "
             "spanning several matches appears as several rows — there is no "
             "spell identifier in this vendor's data.")


def overview(connection):
    """Headline counts, always over CONFIRMED absences unless stated otherwise."""
    result = dict(connection.execute("""
        SELECT
          (SELECT COUNT(*) FROM af_confirmed_absence) AS absences,
          (SELECT COUNT(*) FROM af_absence WHERE type = 'Questionable') AS questionable,
          (SELECT COUNT(*) FROM af_injury) AS injury_rows,
          (SELECT COUNT(DISTINCT league_id) FROM af_confirmed_absence) AS leagues,
          (SELECT COUNT(DISTINCT player_id) FROM af_confirmed_absence) AS players,
          (SELECT COUNT(DISTINCT team_id) FROM af_confirmed_absence) AS teams,
          (SELECT MIN(season) FROM af_confirmed_absence) AS earliest_season,
          (SELECT MAX(season) FROM af_confirmed_absence) AS latest_season
    """).fetchone())
    result["grain_note"] = GRAIN_NOTE
    return result


def quality_metrics(connection):
    return rows(connection, "SELECT metric, value, detail FROM af_data_quality ORDER BY metric")


def reason_categories(connection):
    """Injury / suspension / administrative / unknown split, with the vendor's
    OWN 'Questionable' vs 'Missing Fixture' distinction kept alongside it
    rather than collapsed — the two splits answer different questions."""
    return rows(connection, """
        SELECT r.category, COUNT(*) AS rows_count
        FROM af_absence a JOIN af_reason r ON r.reason = a.reason
        WHERE a.type = 'Missing Fixture'
        GROUP BY r.category ORDER BY rows_count DESC
    """)


AF_DASHBOARD_TOP = 5


def dashboard(connection, top=AF_DASHBOARD_TOP):
    totals = overview(connection)
    return {
        "totals": totals,
        "categories": reason_categories(connection),
        "leagues": rows(connection, """
            SELECT l.id AS league_id, l.name, l.country, COUNT(*) AS absences
            FROM af_confirmed_absence a JOIN af_league l ON l.id = a.league_id
            GROUP BY l.id, l.name, l.country ORDER BY absences DESC, l.name LIMIT ?
        """, (top,)),
        "players": rows(connection, """
            SELECT p.id, p.name, COUNT(*) AS absences,
                   (SELECT SUM(minutes) FROM af_player_season WHERE player_id = p.id) AS minutes
            FROM af_confirmed_absence a JOIN af_player p ON p.id = a.player_id
            GROUP BY p.id, p.name ORDER BY absences DESC, p.name LIMIT ?
        """, (top,)),
        "teams": rows(connection, """
            SELECT t.id, t.name, COUNT(*) AS absences
            FROM af_confirmed_absence a JOIN af_team t ON t.id = a.team_id
            GROUP BY t.id, t.name ORDER BY absences DESC, t.name LIMIT ?
        """, (top,)),
    }


# --------------------------------------------------------------------------- #
# The filterable absence list — mirrors queries.injury_list in shape.
# --------------------------------------------------------------------------- #
_AF_ABSENCE_SELECT = """
    SELECT a.id, a.type, a.reason, a.fixture_date, a.season,
           r.category,
           p.id AS player_id, p.name AS player,
           t.id AS team_id, t.name AS team,
           l.id AS league_id, l.name AS league, l.country,
           f.round, f.status_short
    FROM af_absence a
    JOIN af_reason r ON r.reason = a.reason
    LEFT JOIN af_player p ON p.id = a.player_id
    LEFT JOIN af_team t ON t.id = a.team_id
    LEFT JOIN af_league l ON l.id = a.league_id
    LEFT JOIN af_fixture f ON f.id = a.fixture_id
"""

_AF_SORTABLE = {"fixture_date": "a.fixture_date", "player": "p.name",
                "league": "l.name", "team": "t.name"}

AF_ABSENCE_LIMIT = 50


def absence_list(connection, confirmed_only=True, category=None, league_id=None,
                 season=None, country=None, sort="fixture_date", direction="desc",
                 page=1, per_page=AF_ABSENCE_LIMIT):
    """Filter and paginate absence rows.

    `confirmed_only=True` (the default) excludes 'Questionable' rows — a doubt
    about availability is not the same fact as a confirmed miss, and summing
    them together overstates absences by design, not by accident.
    """
    conditions, params = [], []
    if confirmed_only:
        conditions.append("a.type = 'Missing Fixture'")
    if category:
        conditions.append("r.category = ?")
        params.append(category)
    if league_id:
        conditions.append("a.league_id = ?")
        params.append(league_id)
    if season:
        conditions.append("a.season = ?")
        params.append(season)
    if country:
        conditions.append("l.country = ?")
        params.append(country)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = connection.execute(
        f"SELECT COUNT(*) FROM ({_AF_ABSENCE_SELECT} {where})", params).fetchone()[0]
    page = max(page, 1)
    per_page = min(max(per_page, 1), 200)
    column = _AF_SORTABLE.get(sort, _AF_SORTABLE["fixture_date"])
    order = "ASC" if direction.lower() == "asc" else "DESC"
    items = rows(connection,
                f"{_AF_ABSENCE_SELECT} {where} ORDER BY {column} {order}, a.id DESC "
                f"LIMIT ? OFFSET ?", (*params, per_page, (page - 1) * per_page))
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "grain_note": GRAIN_NOTE}


def filter_options(connection):
    return {
        "countries": [r["country"] for r in rows(
            connection, "SELECT DISTINCT country FROM af_league WHERE country IS NOT NULL ORDER BY country")],
        "categories": [r["category"] for r in rows(
            connection, "SELECT DISTINCT category FROM af_reason ORDER BY category")],
        "seasons": [r["season"] for r in rows(
            connection, "SELECT DISTINCT season FROM af_confirmed_absence ORDER BY season DESC")],
    }


# --------------------------------------------------------------------------- #
# Leagues.
# --------------------------------------------------------------------------- #
def leagues_index(connection):
    return rows(connection, """
        SELECT l.id, l.name, l.country,
               COUNT(DISTINCT ls.season) AS seasons_with_injuries,
               (SELECT COUNT(*) FROM af_confirmed_absence a WHERE a.league_id = l.id) AS absences
        FROM af_league l
        LEFT JOIN af_league_season ls ON ls.league_id = l.id AND ls.has_injuries = 1
        GROUP BY l.id, l.name, l.country
        ORDER BY absences DESC, l.name
    """)


def league_detail(connection, league_id, top=AF_ABSENCE_LIMIT):
    league = connection.execute("SELECT * FROM af_league WHERE id = ?", (league_id,)).fetchone()
    if league is None:
        return None
    by_season = rows(connection, """
        SELECT season, COUNT(*) AS absences,
               SUM(CASE WHEN type = 'Questionable' THEN 1 ELSE 0 END) AS questionable
        FROM af_absence WHERE league_id = ? GROUP BY season ORDER BY season DESC
    """, (league_id,))
    recent = absence_list(connection, league_id=league_id, per_page=top)
    return {"league": dict(league), "by_season": by_season, "recent": recent}


# --------------------------------------------------------------------------- #
# Players — including the rate calculation the minutes crawl was fetched for.
# --------------------------------------------------------------------------- #
AF_PLAYER_INDEX_LIMIT = 100
# A absence per 90 minutes below this many recorded minutes is not a rate,
# it's noise from a handful of appearances. Mirrors the Sportmonks app's
# MINUTES_FLOOR convention (450 there); kept as a separate constant because the
# two datasets' minutes fields are populated differently and should not be
# assumed comparable at the same floor without checking.
AF_MINUTES_FLOOR = 450


def players_index(connection, limit=AF_PLAYER_INDEX_LIMIT):
    total = connection.execute("SELECT COUNT(*) FROM af_player").fetchone()[0]
    items = rows(connection, """
        SELECT p.id, p.name, p.nationality,
               (SELECT COUNT(*) FROM af_confirmed_absence a WHERE a.player_id = p.id) AS absences
        FROM af_player p ORDER BY absences DESC, p.name LIMIT ?
    """, (limit,))
    return {"items": items, "total": total, "shown": len(items)}


def player_detail(connection, player_id):
    player = connection.execute("SELECT * FROM af_player WHERE id = ?", (player_id,)).fetchone()
    if player is None:
        return None
    seasons = rows(connection, """
        SELECT ps.league_id, l.name AS league, ps.season, ps.team_id, t.name AS team,
               ps.position, ps.appearances, ps.lineups, ps.minutes, ps.rating,
               (SELECT COUNT(*) FROM af_confirmed_absence a
                 WHERE a.player_id = ps.player_id AND a.league_id = ps.league_id
                   AND a.season = ps.season) AS absences
        FROM af_player_season ps
        LEFT JOIN af_league l ON l.id = ps.league_id
        LEFT JOIN af_team t ON t.id = ps.team_id
        WHERE ps.player_id = ? ORDER BY ps.season DESC
    """, (player_id,))
    total_minutes = sum(s["minutes"] or 0 for s in seasons)
    # NOT sum(seasons.absences): a player can have confirmed absences in a
    # (league, season) where af_player_season has no row for them at all (no
    # statistics recorded — the same reason 120 players are absent from
    # af_player entirely, see logbook 2026-07-30). Summing only the mapped
    # seasons would silently undercount the headline total for exactly the
    # players whose season coverage is thinnest.
    total_absences = connection.execute(
        "SELECT COUNT(*) FROM af_confirmed_absence WHERE player_id = ?",
        (player_id,)).fetchone()[0]
    rate = (total_absences / (total_minutes / 90)) if total_minutes >= AF_MINUTES_FLOOR else None
    recent = rows(connection, f"""
        {_AF_ABSENCE_SELECT} WHERE a.player_id = ? AND a.type = 'Missing Fixture'
        ORDER BY a.fixture_date DESC LIMIT ?
    """, (player_id, AF_ABSENCE_LIMIT))
    return {
        "player": dict(player), "seasons": seasons, "recent": recent,
        "total_minutes": total_minutes, "total_absences": total_absences,
        "rate_per_90": round(rate, 3) if rate is not None else None,
        "minutes_floor": AF_MINUTES_FLOOR, "grain_note": GRAIN_NOTE,
        "transfers": player_transfers(connection, player_id),
    }


# --------------------------------------------------------------------------- #
# Transfers.
#
# Two notes every caller must carry, both measured 2026-07-30:
#
# 1. Dates are trustworthy to the SEASON, not the day. They cluster hard on
#    July 1 (the season boundary) and on batch-stamped days, so no query here
#    computes an interval in days from a transfer.
# 2. A club side can have a name and no id — the vendor sometimes puts a PLAYER
#    in the club field. Templates must render an id-less side as plain text.
#    The `*_linkable` flags below exist so a template cannot get that wrong by
#    forgetting to check.
# --------------------------------------------------------------------------- #
TRANSFER_DATE_NOTE = ("Transfer dates are reliable to the season, not the day: "
                      "the vendor stamps many moves as 1 July and batches "
                      "others onto a single date.")
TRANSFER_FEE_NOTE = ("Fees are parsed out of a free-text field that also holds "
                     "categories like 'Loan' and 'Free'. Only about a fifth of "
                     "moves carry one, so a fee total is a floor, not a market "
                     "value — and it excludes any fee the vendor did not "
                     "denominate in euros.")

AF_TRANSFER_LIMIT = 50


def transfers_available(connection):
    """Whether this database was built with the transfer tables at all.

    **`apifootball.db` is a committed binary artifact**, so the schema in
    `schema_af.sql` and the schema actually deployed are two different things
    that move at different times: code ships on push, the database ships only
    when someone re-runs the ETL and commits the rebuilt file. Between those
    two moments the deployed app is running new queries against an old file.

    That gap already broke production once — every `/af/player/{id}` and
    `/af/team/{id}` page returned 500 with `no such table: af_transfer`,
    because transfers were wired into `player_detail` and `team_detail` as a
    hard dependency. Those pages have nothing to do with transfers and had
    worked for weeks.

    So this is checked rather than assumed. An absent table means "not built
    yet", which callers must render differently from "this player never moved"
    — the two are opposite claims and only one of them is about football.
    """
    return connection.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'table' AND name = 'af_transfer'").fetchone()[0] > 0


def _no_transfer_data(**extra):
    """The shape every transfer query returns when the tables are absent.

    `available` is False and every total is zero, so a template can say "not
    loaded" instead of silently showing a zero that reads as a measurement.
    """
    return {"rows": [], "total": 0, "shown": 0, "available": False,
            "date_note": TRANSFER_DATE_NOTE, **extra}


# The list key is `rows`, NOT `items`, and that is load-bearing. These dicts are
# read from templates as nested values (`transfers.rows`,
# `transfers.incoming.rows`), and Jinja resolves attributes before keys — so
# `transfers.items` returns the built-in `dict.items` METHOD, not the list, and
# iterating it raises "'builtin_function_or_method' object is not iterable".
#
# The other `items`-keyed dicts in this module are safe only because their
# routes `**`-unpack them into top-level template variables, where `items` is a
# plain name with no dict in front of it. Anything nested must avoid the name.


_AF_TRANSFER_SELECT = """
    SELECT t.id, t.player_id, t.player_name, t.date, t.type, t.source,
           t.from_team_id, t.from_team_name, t.to_team_id, t.to_team_name,
           tt.category, tt.fee_eur, tt.fee_amount, tt.fee_currency,
           t.from_team_id IS NOT NULL AS from_linkable,
           t.to_team_id IS NOT NULL AS to_linkable
    FROM af_transfer t
    LEFT JOIN af_transfer_type tt ON tt.type = t.type
"""


def player_transfers(connection, player_id, limit=AF_TRANSFER_LIMIT):
    """One player's career, newest first, with its real total alongside.

    Deliberately NOT restricted to players present in af_player: most of these
    people predate the 2020–2025 window every other table is capped to, so
    requiring an af_player row would discard the history that makes this table
    worth having.
    """
    if not transfers_available(connection):
        return _no_transfer_data()
    total = connection.execute(
        "SELECT COUNT(*) FROM af_transfer WHERE player_id = ?",
        (player_id,)).fetchone()[0]
    items = rows(connection, f"""
        {_AF_TRANSFER_SELECT} WHERE t.player_id = ?
        ORDER BY t.date DESC, t.id DESC LIMIT ?
    """, (player_id, limit))
    return {"rows": items, "total": total, "shown": len(items),
            "available": True, "date_note": TRANSFER_DATE_NOTE}


def team_transfers(connection, team_id, limit=AF_TRANSFER_LIMIT):
    """Moves in and out of one club, counted separately.

    Two queries rather than one with a direction column: a club's incoming and
    outgoing business are different questions, and a combined list ordered by
    date reads as a single flow that hides which is which.
    """
    if not transfers_available(connection):
        return {"available": False, "date_note": TRANSFER_DATE_NOTE,
                "incoming": _no_transfer_data(), "outgoing": _no_transfer_data()}
    result = {"available": True, "date_note": TRANSFER_DATE_NOTE}
    for direction, column in (("incoming", "to_team_id"),
                              ("outgoing", "from_team_id")):
        total = connection.execute(
            f"SELECT COUNT(*) FROM af_transfer WHERE {column} = ?",
            (team_id,)).fetchone()[0]
        items = rows(connection, f"""
            {_AF_TRANSFER_SELECT} WHERE t.{column} = ?
            ORDER BY t.date DESC, t.id DESC LIMIT ?
        """, (team_id, limit))
        result[direction] = {"rows": items, "total": total, "shown": len(items)}
    return result


def transfer_categories(connection):
    """The category split, with euro fees summed only where they exist.

    `fee_rows` is returned beside `fee_eur_total` on purpose: a total with no
    denominator invites reading it as the category's whole value, when most
    rows in every category carry no fee at all.
    """
    if not transfers_available(connection):
        return []
    return rows(connection, """
        SELECT COALESCE(tt.category, 'unmapped') AS category,
               COUNT(*) AS moves,
               COUNT(tt.fee_eur) AS fee_rows,
               COALESCE(SUM(tt.fee_eur), 0) AS fee_eur_total
        FROM af_transfer t
        LEFT JOIN af_transfer_type tt ON tt.type = t.type
        GROUP BY category ORDER BY moves DESC
    """)


def transfers_by_year(connection, limit=40):
    """Moves per calendar year — the shape of the historical reach.

    Grouped by year rather than season because a transfer has no season: it is
    dated, and the vendor's own July-1 stamping means a "season" derived from
    that date would be an inference dressed as a fact.
    """
    if not transfers_available(connection):
        return []
    return rows(connection, """
        SELECT SUBSTR(date, 1, 4) AS year, COUNT(*) AS moves
        FROM af_transfer WHERE date IS NOT NULL AND date <> ''
        GROUP BY year ORDER BY year DESC LIMIT ?
    """, (limit,))


def transfer_overview(connection):
    """Headline transfer figures, each stated so it cannot be over-read."""
    if not transfers_available(connection):
        # Every key the template reads, so the page renders its "not built yet"
        # state instead of raising a missing-attribute error — which would be
        # the same 500 in a different costume.
        return {"moves": 0, "players": 0, "earliest": None, "latest": None,
                "fee_rows": 0, "fee_eur_total": 0, "confirmed_both": 0,
                "unlinkable_sides": 0, "available": False,
                "date_note": TRANSFER_DATE_NOTE, "fee_note": TRANSFER_FEE_NOTE}
    result = dict(connection.execute("""
        SELECT
          (SELECT COUNT(*) FROM af_transfer) AS moves,
          (SELECT COUNT(DISTINCT player_id) FROM af_transfer) AS players,
          (SELECT MIN(date) FROM af_transfer WHERE date IS NOT NULL AND date <> '')
            AS earliest,
          (SELECT MAX(date) FROM af_transfer WHERE date IS NOT NULL AND date <> '')
            AS latest,
          (SELECT COUNT(*) FROM af_transfer_detail WHERE fee_eur IS NOT NULL)
            AS fee_rows,
          (SELECT COALESCE(SUM(fee_eur), 0) FROM af_transfer_detail) AS fee_eur_total,
          -- Moves reported by both a club and the player: agreement, not extra
          -- volume. Kept visible because the ETL's dedup depends on it.
          (SELECT COUNT(*) FROM af_transfer WHERE source = 'both') AS confirmed_both,
          -- Club sides the app must render as plain text, never as a link.
          (SELECT COUNT(*) FROM af_transfer
            WHERE from_team_id IS NULL OR to_team_id IS NULL) AS unlinkable_sides
    """).fetchone())
    result["available"] = True
    result["date_note"] = TRANSFER_DATE_NOTE
    result["fee_note"] = TRANSFER_FEE_NOTE
    return result


# --------------------------------------------------------------------------- #
# Teams.
# --------------------------------------------------------------------------- #
def teams_index(connection):
    return rows(connection, """
        SELECT t.id, t.name, t.country,
               (SELECT COUNT(*) FROM af_confirmed_absence a WHERE a.team_id = t.id) AS absences
        FROM af_team t ORDER BY absences DESC, t.name
    """)


def team_detail(connection, team_id, top=AF_ABSENCE_LIMIT):
    team = connection.execute("SELECT * FROM af_team WHERE id = ?", (team_id,)).fetchone()
    if team is None:
        return None
    recent = rows(connection, f"""
        {_AF_ABSENCE_SELECT} WHERE a.team_id = ? AND a.type = 'Missing Fixture'
        ORDER BY a.fixture_date DESC LIMIT ?
    """, (team_id, top))
    return {"team": dict(team), "recent": recent,
            "transfers": team_transfers(connection, team_id)}


# --------------------------------------------------------------------------- #
# Analytics.
# --------------------------------------------------------------------------- #
def by_position(connection):
    """Position comes from af_player_season (season-scoped), not af_player —
    the vendor reports it per competition-season, which is more honest than a
    single career position since players move. A player appearing in several
    seasons is counted once per season here, matching how the field is stored."""
    return rows(connection, """
        SELECT COALESCE(ps.position, 'Unknown') AS position,
               COUNT(DISTINCT a.id) AS absences
        FROM af_confirmed_absence a
        LEFT JOIN af_player_season ps
          ON ps.player_id = a.player_id AND ps.league_id = a.league_id AND ps.season = a.season
        GROUP BY position ORDER BY absences DESC, position
    """)


def by_age_band(connection):
    """Age at the time of the absence, computed from birth_date + fixture_date
    (both ISO strings), so a player's band reflects their age when it happened
    rather than their age today."""
    return rows(connection, """
        SELECT CASE WHEN p.birth_date IS NULL THEN 'Unknown'
                    WHEN age < 20 THEN 'Under 20' WHEN age < 25 THEN '20-24'
                    WHEN age < 30 THEN '25-29' WHEN age < 35 THEN '30-34'
                    ELSE '35+' END AS band,
               COUNT(*) AS absences
        FROM (
          SELECT a.id, (julianday(a.fixture_date) - julianday(p.birth_date)) / 365.25 AS age,
                 p.birth_date
          FROM af_confirmed_absence a LEFT JOIN af_player p ON p.id = a.player_id
        ) AS p
        GROUP BY band
        ORDER BY CASE band WHEN 'Under 20' THEN 1 WHEN '20-24' THEN 2
                           WHEN '25-29' THEN 3 WHEN '30-34' THEN 4
                           WHEN '35+' THEN 5 ELSE 6 END
    """)


def by_reason(connection, limit=15):
    return rows(connection, """
        SELECT a.reason, r.category, COUNT(*) AS absences
        FROM af_confirmed_absence a JOIN af_reason r ON r.reason = a.reason
        GROUP BY a.reason, r.category ORDER BY absences DESC LIMIT ?
    """, (limit,))


def by_league(connection):
    return rows(connection, """
        SELECT l.id AS league_id, COALESCE(l.country, 'Unknown') AS country,
               COALESCE(l.name, 'Unknown') AS league, COUNT(*) AS absences
        FROM af_confirmed_absence a LEFT JOIN af_league l ON l.id = a.league_id
        GROUP BY l.id, country, league ORDER BY absences DESC, league
    """)


def by_month(connection):
    return rows(connection, """
        SELECT strftime('%m', fixture_date) AS month, COUNT(*) AS absences
        FROM af_confirmed_absence WHERE fixture_date IS NOT NULL
        GROUP BY month ORDER BY month
    """)


def search(connection, query, per_kind=8):
    """Prefix search across players/teams/leagues, mirroring queries.search."""
    if not query or not query.strip():
        return []
    pattern = query.strip().replace("%", r"\%").replace("_", r"\_") + "%"
    results = []
    for kind, sql in (
        ("af-player", "SELECT id, name AS label FROM af_player WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?"),
        ("af-team", "SELECT id, name AS label FROM af_team WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?"),
        ("af-league", "SELECT id, name AS label FROM af_league WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?"),
    ):
        for row in rows(connection, sql, (pattern, per_kind)):
            results.append({"kind": kind, **row})
    return results
