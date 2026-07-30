"""Tests for app/af_queries.py against the `af_connection` fixture in conftest.py.

See conftest.py for the dataset shape — it deliberately covers the edge cases
this schema exists to get right (confirmed vs Questionable, an orphan player
absent from af_player, the minutes floor, category classification).
"""
import sqlite3

import pytest

from app import af_queries
from app import db as db_module


# --------------------------------------------------------------------------- #
# Grain: confirmed vs Questionable must never be conflated.
# --------------------------------------------------------------------------- #
def test_overview_excludes_questionable_from_the_headline_count(af_connection):
    result = af_queries.overview(af_connection)
    assert result["absences"] == 5          # 6 rows total, 1 is Questionable
    assert result["questionable"] == 1
    # af_injury = confirmed AND category='injury'. Of the 5 confirmed rows,
    # 2 are player 1's Hamstring absences and 1 is player 3's — the other 2
    # confirmed rows (player 1 fixture 3, player 2 fixture 1) are 'Suspended'.
    assert result["injury_rows"] == 3


def test_absence_list_confirmed_only_excludes_questionable_by_default(af_connection):
    result = af_queries.absence_list(af_connection)
    assert result["total"] == 5
    assert all(row["type"] == "Missing Fixture" for row in result["items"])


def test_absence_list_can_include_questionable(af_connection):
    result = af_queries.absence_list(af_connection, confirmed_only=False)
    assert result["total"] == 6
    assert any(row["type"] == "Questionable" for row in result["items"])


# --------------------------------------------------------------------------- #
# Reason categorisation.
# --------------------------------------------------------------------------- #
def test_reason_categories_split_injury_from_suspension(af_connection):
    categories = {row["category"]: row["rows_count"] for row in af_queries.reason_categories(af_connection)}
    assert categories == {"injury": 3, "suspension": 2}


def test_absence_list_filters_by_category(af_connection):
    result = af_queries.absence_list(af_connection, category="suspension")
    assert result["total"] == 2
    assert all(row["category"] == "suspension" for row in result["items"])


# --------------------------------------------------------------------------- #
# Orphan players: absent from af_player, but their absences still count.
# --------------------------------------------------------------------------- #
def test_orphan_player_absences_still_counted_in_totals(af_connection):
    # Player 3 has no af_player row; their one absence must still be visible
    # in the overview total and in team/league rollups.
    assert af_queries.overview(af_connection)["absences"] == 5
    team = af_queries.team_detail(af_connection, 100)
    assert len(team["recent"]) == 5


def test_player_detail_returns_none_for_missing_player(af_connection):
    assert af_queries.player_detail(af_connection, 3) is None  # no af_player row
    assert af_queries.player_detail(af_connection, 999) is None  # doesn't exist at all


# --------------------------------------------------------------------------- #
# Rates: the minutes floor, and NOT summing only player_season-mapped rows.
# --------------------------------------------------------------------------- #
def test_player_rate_computed_above_the_minutes_floor(af_connection):
    detail = af_queries.player_detail(af_connection, 1)
    assert detail["total_minutes"] == 900
    assert detail["total_absences"] == 3   # confirmed only, Questionable excluded
    assert detail["rate_per_90"] == pytest.approx(3 / (900 / 90))


def test_player_rate_is_none_below_the_minutes_floor(af_connection):
    detail = af_queries.player_detail(af_connection, 2)
    assert detail["total_minutes"] == 100
    assert detail["rate_per_90"] is None  # below AF_MINUTES_FLOOR — not zero


def test_total_absences_is_not_just_the_sum_of_mapped_seasons(af_db_path):
    # Regression guard: an earlier version summed player_season.absences,
    # which only reflects (league, season) pairs present in af_player_season.
    # Add an absence in a league/season this player has NO player_season row
    # for, and confirm the headline total still includes it.
    #
    # af_connection is opened mode=ro (matching app.db's own "opened read-only"
    # invariant), so this writes through a SEPARATE connection to the same
    # file, then opens its own read-only connection afterward — af_connection
    # itself is not used here because it would already be open (and read-only)
    # before this test body runs.
    writer = sqlite3.connect(af_db_path)
    writer.execute("INSERT INTO af_league (id, name, country) VALUES (20, 'Other League', 'Otherland')")
    writer.execute(
        "INSERT INTO af_fixture (id, league_id, season, date, home_team_id, away_team_id) "
        "VALUES (5, 20, 2025, '2025-01-01T00:00:00+00:00', 100, 100)")
    writer.execute("INSERT INTO af_reason (reason, category, row_count) VALUES ('Knock', 'injury', 1)")
    writer.execute(
        "INSERT INTO af_absence (player_id, fixture_id, team_id, league_id, season, type, reason, fixture_date) "
        "VALUES (1, 5, 100, 20, 2025, 'Missing Fixture', 'Knock', '2025-01-01T00:00:00+00:00')")
    writer.commit()
    writer.close()

    connection = db_module.connect_af(af_db_path)
    try:
        detail = af_queries.player_detail(connection, 1)
        assert detail["total_absences"] == 4  # 3 original + 1 in an unmapped season
        # But the per-season breakdown correctly shows 0 for that season, since
        # there is no player_season row to attach it to — this is the
        # trade-off the fix documents, not a second bug.
        assert sum(s["absences"] for s in detail["seasons"]) == 3
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# Position is season-scoped, from af_player_season — not a player attribute.
# --------------------------------------------------------------------------- #
def test_by_position_reads_from_player_season_not_player(af_connection):
    positions = {row["position"]: row["absences"] for row in af_queries.by_position(af_connection)}
    # Player 1 (Defender) has ALL 3 of his confirmed absences map to Defender —
    # one player_season row covers the whole league/season, not per-fixture.
    # Player 2 (Forward) has 1; player 3 has no player_season row -> 'Unknown'.
    assert positions["Defender"] == 3
    assert positions["Forward"] == 1
    assert positions["Unknown"] == 1


def test_by_age_band_uses_age_at_fixture_date_not_today(af_connection):
    bands = {row["band"]: row["absences"] for row in af_queries.by_age_band(af_connection)}
    # Player 1 born 2000-01-01, absences in 2024 -> 24 years old -> '20-24'.
    assert bands.get("20-24", 0) >= 2


# --------------------------------------------------------------------------- #
# Leagues / teams index and detail.
# --------------------------------------------------------------------------- #
def test_league_detail_by_season_breakdown(af_connection):
    detail = af_queries.league_detail(af_connection, 10)
    assert detail["league"]["name"] == "Test League"
    row = next(r for r in detail["by_season"] if r["season"] == 2024)
    assert row["absences"] == 6 and row["questionable"] == 1


def test_league_detail_returns_none_for_unknown_league(af_connection):
    assert af_queries.league_detail(af_connection, 999) is None


def test_leagues_index_counts_confirmed_absences_only(af_connection):
    row = next(r for r in af_queries.leagues_index(af_connection) if r["id"] == 10)
    assert row["absences"] == 5
