"""The league and season dimensions, and the absences that hang off them.

Both dimensions used to come from coverage.db alone, which only ever held the
domestic leagues `ingest/resolve.py` swept. Every cup competition was therefore
missing from both, and the absences belonging to one pointed at a league_id and
a season_id that did not exist — 11,118 of 26,408 on 2026-07-28, rendered with a
blank competition and invisible to any query that joins the dimension.
"""
import json
import sqlite3

import pytest

from app import etl


@pytest.fixture
def cup_cache_dir(tmp_path):
    """A fixture cache holding a cup month as well as a domestic one.

    The standard raw_cache_dir only has league 10, which coverage.db knows
    about — so an orphan check over it passes even against the broken build.
    The absence that exposes the bug has to belong to a competition that exists
    ONLY in the cached seasons files, exactly as the real cup absences do.
    """
    directory = tmp_path / "cup_fixtures"
    directory.mkdir()

    def month(league_id, season_id, sideline_id, player_id):
        return json.dumps({"league_id": league_id, "fixtures": [
            {"id": sideline_id, "season_id": season_id, "sidelined": [
                {"id": sideline_id * 10, "sideline_id": sideline_id,
                 "sideline": {"id": sideline_id, "player_id": player_id, "type_id": 500,
                              "category": "injury", "team_id": 100,
                              "start_date": "2025-02-01", "end_date": "2025-04-01",
                              "games_missed": 3, "completed": True}},
            ]},
        ]})

    (directory / "10_2025-03.json").write_text(month(10, 77, 900, 5001))
    # League 2 / season 23619: present in seasons_dir, absent from coverage.db.
    (directory / "2_2025-03.json").write_text(month(2, 23619, 910, 5001))
    return directory


def test_season_stores_its_date_window(tmp_path, raw_cache_dir, reference_db,
                                       seasons_dir, countries_file):
    """Transfers carry a date but no season_id, so bucketing them needs real
    season windows. Every cached season has starting_at/ending_at, so the
    dimension keeps them rather than guessing at league calendars."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    assert connection.execute(
        "SELECT starting_at, ending_at FROM season WHERE id = 23619"
    ).fetchone() == ("2024-07-09", "2025-05-31")  # the real window for this season


def test_cup_competitions_reach_the_league_dimension(tmp_path, raw_cache_dir, reference_db,
                                                     seasons_dir, countries_file):
    """coverage.db knows only the domestic leagues it swept. League 2 exists
    solely in the cached seasons files, and its country arrives as an id that
    only countries.json can resolve — so this fails against the old build."""
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    assert connection.execute(
        "SELECT country, name FROM league WHERE id = 2").fetchone() == ("Europe", "Champions League")
    assert connection.execute(
        "SELECT league_id, name FROM season WHERE id = 23619").fetchone() == (2, "2024/2025")


def test_no_absence_is_orphaned_from_its_competition(tmp_path, cup_cache_dir, reference_db,
                                                     seasons_dir, countries_file):
    """42% of real absences pointed at a league_id and season_id absent from the
    dimensions, so they rendered a blank competition and would vanish from any
    grid that joins one."""
    output = tmp_path / "app.db"
    etl.build(cup_cache_dir, reference_db, output,
              seasons_dir=seasons_dir, countries_file=countries_file)
    connection = sqlite3.connect(output)

    # Guards against a vacuous pass: zero orphans is only meaningful if the cup
    # absence is actually in the table.
    assert connection.execute("SELECT COUNT(*) FROM absence WHERE league_id = 2").fetchone()[0] == 1
    assert connection.execute("""
        SELECT COUNT(*) FROM absence a
        LEFT JOIN league l ON l.id = a.league_id WHERE l.id IS NULL""").fetchone()[0] == 0
    assert connection.execute("""
        SELECT COUNT(*) FROM absence a
        LEFT JOIN season s ON s.id = a.season_id WHERE s.id IS NULL""").fetchone()[0] == 0


def test_coverage_db_still_fills_what_the_cache_lacks(tmp_path, raw_cache_dir, reference_db,
                                                      countries_file):
    """The cache is the wider source, not the only one. With no cache at all the
    build must degrade to the old dimensions rather than losing every row —
    otherwise a machine without data/raw silently produces an empty app."""
    empty = tmp_path / "no_seasons"
    empty.mkdir()
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output,
              seasons_dir=empty, countries_file=countries_file)
    connection = sqlite3.connect(output)

    assert connection.execute(
        "SELECT country, name FROM league WHERE id = 10").fetchone() == ("Testland", "Test League")
    assert connection.execute(
        "SELECT name, is_current, starting_at FROM season WHERE id = 77").fetchone() == (
            "2024/2025", 1, None)  # no dates: coverage.db doesn't record them
