"""fixture_coverage: fixture counts per league-season, aggregated during the
same cache scan collect_absences already performs.

A club competes in its domestic league AND a UEFA cup in the same period, so
one cached file (one league, one month) can hold fixtures for more than one
season_id — exactly the shape of bug Slice A fixed for absences. These tests
guard against counting a fixture towards the wrong season, or a file that
touches two seasons contributing more than one month to either.
"""
import json
import sqlite3
from urllib.parse import quote

import pytest

from app import db, etl, matrix


@pytest.fixture
def multi_season_cache_dir(tmp_path):
    """One league whose fixtures split across two seasons within a single
    file, plus a second file (same league, same season) in another month.

    The split-file case catches double-counting across season_ids; the second
    month catches non_empty_months being counted per file rather than per
    (league, season) pair.
    """
    directory = tmp_path / "multi_season_fixtures"
    directory.mkdir()

    def fixture(fixture_id, season_id):
        return {"id": fixture_id, "season_id": season_id, "sidelined": []}

    # March: two fixtures in season 100 (the domestic league), one in season
    # 200 (a cup running concurrently).
    (directory / "20_2025-03.json").write_text(json.dumps({"league_id": 20, "fixtures": [
        fixture(1, 100), fixture(2, 100), fixture(3, 200),
    ]}))
    # April: one more season-100 fixture, in a different month.
    (directory / "20_2025-04.json").write_text(json.dumps({"league_id": 20, "fixtures": [
        fixture(4, 100),
    ]}))
    return directory


def test_fixture_coverage_counts_cached_fixtures(tmp_path, raw_cache_dir, reference_db,
                                                  seasons_dir, countries_file):
    """raw_cache_dir holds one league-10 file with 2 fixtures, both season 77."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    assert connection.execute(
        "SELECT fixtures, non_empty_months FROM fixture_coverage "
        "WHERE league_id = 10 AND season_id = 77").fetchone() == (2, 1)


def test_fixtures_split_across_seasons_are_not_double_counted(tmp_path, multi_season_cache_dir,
                                                                reference_db, seasons_dir, countries_file):
    """The trap Slice A already hit once: a single cached file can carry
    fixtures for two different season_ids (domestic league + concurrent cup).
    Each must be attributed to its own season, once each — not summed
    together and not double-counted onto either."""
    output = tmp_path / "app.db"
    etl.build(multi_season_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    # Season 100: 2 fixtures in March + 1 in April = 3 fixtures, 2 distinct months.
    assert connection.execute(
        "SELECT fixtures, non_empty_months FROM fixture_coverage "
        "WHERE league_id = 20 AND season_id = 100").fetchone() == (3, 2)
    # Season 200: 1 fixture, seen only in March — must not inherit season
    # 100's count, and must not count March twice for season 100 either.
    assert connection.execute(
        "SELECT fixtures, non_empty_months FROM fixture_coverage "
        "WHERE league_id = 20 AND season_id = 200").fetchone() == (1, 1)

    total_fixtures = connection.execute("SELECT SUM(fixtures) FROM fixture_coverage").fetchone()[0]
    assert total_fixtures == 4  # 3 in season 100 + 1 in season 200, never double-counted


# --- app/matrix.py: the pivot ------------------------------------------------
#
# `connection` (tests/conftest.py) builds from raw_cache_dir + players_dir +
# seasons_dir: league 10 has 3 absences (all team 100, season 77) and player
# 5001 has 944 minutes in season 77 while player 5003 has 500 in season 78 at
# the same team — enough to exercise multiple seasons in one row without a
# dedicated fixture. seasons_dir also adds league 2 (Champions League) with
# zero data of any kind, which is what proves a league still renders as a
# blank row rather than vanishing.


def test_pivots_absences_into_season_columns(connection):
    result = matrix.build(connection, "absences", scope="league")

    league = next(row for row in result["rows"] if row["id"] == 10)
    assert league["cells"]["2024/2025"] == 3
    assert league["total"] == 3


def test_league_with_no_data_still_renders_as_a_blank_row(connection):
    """League 2 (Champions League) reached the dimension via seasons_dir but
    has no absences at all in this fixture. Coverage means it must still
    appear — a league silently missing looks like a gap in the app, not the
    dataset. Empty and zero are different claims: this row shows no `0`."""
    result = matrix.build(connection, "absences", scope="league")

    league = next(row for row in result["rows"] if row["id"] == 2)
    assert league["cells"] == {}
    assert league["total"] == 0


def test_empty_and_zero_are_different(connection):
    result = matrix.build(connection, "absences", scope="league")
    league = next(row for row in result["rows"] if row["id"] == 10)

    assert "2023/2024" not in league["cells"]  # absent, not zero — league 10 had no absences that season


def test_minutes_spans_multiple_seasons_in_one_row(connection):
    """Player 5001 (944 minutes, season 77) and player 5003 (500 minutes,
    season 78) sit at the same club, so the club/league row must carry both
    season columns rather than collapsing or overwriting one."""
    result = matrix.build(connection, "minutes", scope="league")
    league = next(row for row in result["rows"] if row["id"] == 10)

    assert league["cells"]["2024/2025"] == 944
    assert league["cells"]["2023/2024"] == 500
    assert league["total"] == 1444


def test_club_scope_narrows_to_one_league(connection):
    result = matrix.build(connection, "absences", scope="club", scope_id=10)

    assert [row["label"] for row in result["rows"]] == ["FC Test"]
    assert result["rows"][0]["total"] == 3


def test_player_scope_narrows_to_one_club(connection):
    result = matrix.build(connection, "absences", scope="player", scope_id=100)

    by_label = {row["label"]: row["total"] for row in result["rows"]}
    assert by_label == {"A. Player": 1, "C. Player": 1}  # players 5001 and 5003; 5002 unresolved, dropped


def test_fixtures_measure_has_no_club_or_player_scope():
    assert matrix.MEASURES["fixtures"].supports("league")
    assert not matrix.MEASURES["fixtures"].supports("club")
    assert not matrix.MEASURES["fixtures"].supports("player")
    with pytest.raises(ValueError):
        matrix.build(sqlite3.connect(":memory:"), "fixtures", scope="club", scope_id=1)


def test_transfers_outside_every_season_window_are_unmatched(connection):
    """players_dir's transfers for player 5001 are all dated 2019-2022, years
    before either cached season window (77 starts 2024-08-16, 78 starts
    2023-08-11) — none can be placed in a league row, so they must be
    reported as unmatched rather than silently dropped or misattributed."""
    result = matrix.build(connection, "transfers", scope="league")

    assert result["unmatched"] == 4
    assert result["unattributed"] == 4
    for row in result["rows"]:
        assert row["cells"] == {}


def test_transfer_lands_in_the_season_its_date_falls_within(tmp_path, raw_cache_dir, reference_db,
                                                              seasons_dir, countries_file):
    """A transfer dated inside season 77's window, to a team with a roster
    row in that season, must land in that season's column — the positive
    case the unmatched test above doesn't cover."""
    players = tmp_path / "transfer_players"
    players.mkdir()
    (players / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [{"player_id": 5001, "season_id": 77, "team_id": 100,
                        "details": [{"type_id": 119, "value": {"total": 944}}]}],
        "transfers": [{"id": 800, "player_id": 5001, "from_team_id": 200, "to_team_id": 100,
                       "date": "2024-09-01", "type_id": 219, "amount": 1000000,
                       "completed": True, "career_ended": False}],
    }))
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=players,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = db.connect(output)

    result = matrix.build(connection, "transfers", scope="league")
    league = next(row for row in result["rows"] if row["id"] == 10)
    assert league["cells"]["2024/2025"] == 1
    assert result["unmatched"] == 0


# --- /admin routes ------------------------------------------------------


def test_admin_index_lists_every_measure(client):
    body = client.get("/sportmonks/admin").text
    for measure in ("absences", "transfers", "minutes", "fixtures"):
        assert f"/admin/matrix/{measure}" in body


def test_matrix_page_renders_a_grid(client):
    response = client.get("/sportmonks/admin/matrix/absences")
    assert response.status_code == 200
    assert "2024/2025" in response.text


def test_unknown_measure_is_404(client):
    assert client.get("/sportmonks/admin/matrix/nonsense").status_code == 404


def test_league_rows_drill_into_clubs(client):
    assert 'href="/sportmonks/admin/matrix/absences/league/10"' in client.get("/sportmonks/admin/matrix/absences").text


def test_club_scope_page_drills_into_players(client):
    body = client.get("/sportmonks/admin/matrix/absences/league/10").text
    assert 'href="/sportmonks/admin/matrix/absences/team/100"' in body


def test_unknown_league_in_drill_down_is_404(client):
    assert client.get("/sportmonks/admin/matrix/absences/league/999999").status_code == 404


def test_unknown_team_in_drill_down_is_404(client):
    assert client.get("/sportmonks/admin/matrix/absences/team/999999").status_code == 404


def test_fixtures_measure_has_no_drill_down_link(client):
    """fixture_coverage carries no club/player dimension, so unlike every
    other measure the league row must render as plain text, not a link."""
    body = client.get("/sportmonks/admin/matrix/fixtures").text
    assert 'href="/sportmonks/admin/matrix/fixtures/league/' not in body


def test_fixtures_club_scope_route_is_404(client):
    """Not just unlinked — genuinely unreachable, since matrix.build() raises
    for a scope a measure doesn't support."""
    assert client.get("/sportmonks/admin/matrix/fixtures/league/10").status_code == 404


# --- cell-level detail ----------------------------------------------------


def test_cell_detail_lists_absences_for_player_and_season(connection):
    records = matrix.cell_detail(connection, "absences", 5001, "2024/2025")

    assert len(records) == 1
    assert records[0]["category"] == "injury"
    assert records[0]["team_name"] == "FC Test"
    assert records[0]["type_name"] == "Knock"


def test_cell_detail_unsupported_measure_raises():
    with pytest.raises(ValueError):
        matrix.cell_detail(sqlite3.connect(":memory:"), "minutes", 1, "2024/2025")


def test_cell_detail_lists_transfers_for_player_and_season(tmp_path, raw_cache_dir, reference_db,
                                                             seasons_dir, countries_file):
    players = tmp_path / "cell_transfer_players"
    players.mkdir()
    (players / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [{"player_id": 5001, "season_id": 77, "team_id": 100,
                        "details": [{"type_id": 119, "value": {"total": 944}}]}],
        "transfers": [{"id": 800, "player_id": 5001, "from_team_id": 200, "to_team_id": 100,
                       "date": "2024-09-01", "type_id": 219, "amount": 1000000,
                       "completed": True, "career_ended": False}],
    }))
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=players,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = db.connect(output)

    records = matrix.cell_detail(connection, "transfers", 5001, "2024/2025")
    assert len(records) == 1
    assert records[0]["from_team_name"] == "FC Rival"
    assert records[0]["to_team_name"] == "FC Test"
    assert records[0]["amount"] == 1000000


def test_player_scope_cells_link_to_detail(client):
    """Jinja's `urlencode` filter leaves `/` unescaped in a plain string —
    fine here, since a query value's `/` doesn't need escaping (the browser
    and FastAPI's parser both split on `&`/`=`, not `/`)."""
    body = client.get("/sportmonks/admin/matrix/absences/team/100").text
    assert 'href="/sportmonks/admin/matrix/absences/player/5001/detail?season=2024/2025"' in body


def test_cell_detail_page_shows_the_underlying_records(client):
    response = client.get("/sportmonks/admin/matrix/absences/player/5001/detail", params={"season": "2024/2025"})
    assert response.status_code == 200
    assert "FC Test" in response.text


def test_minutes_cells_are_never_linked(client):
    """Minutes has no cell_detail path — the number in the cell already IS
    the record; there is nothing further to list."""
    body = client.get("/sportmonks/admin/matrix/minutes/team/100").text
    assert "/detail?season=" not in body


def test_cell_detail_for_unsupported_measure_is_404(client):
    assert client.get("/sportmonks/admin/matrix/minutes/player/5001/detail",
                      params={"season": "2024/2025"}).status_code == 404


def test_cell_detail_unknown_player_is_404(client):
    assert client.get("/sportmonks/admin/matrix/absences/player/999999/detail",
                      params={"season": "2024/2025"}).status_code == 404
