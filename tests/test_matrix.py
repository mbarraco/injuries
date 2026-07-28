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

import pytest

from app import etl


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
