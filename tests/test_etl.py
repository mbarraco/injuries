import json
import sqlite3

from app import etl


def test_keeps_every_category_and_dedupes(tmp_path, raw_cache_dir, reference_db):
    output = tmp_path / "app.db"
    result = etl.build(raw_cache_dir, reference_db, output)
    connection = sqlite3.connect(output)

    # The injury view still exposes only injury-category rows, deduped by id.
    assert connection.execute("SELECT id, fixture_appearances FROM injury ORDER BY id").fetchall() == [(900, 2), (902, 1)]
    # ...but the suspension is no longer dropped — it lives in the base table.
    assert connection.execute("SELECT id, category FROM absence WHERE category = 'suspended'").fetchall() == [(901, "suspended")]
    assert connection.execute("SELECT COUNT(*) FROM absence").fetchone()[0] == 3
    assert result == {"absences": 3, "injuries": 2, "categories": {"injury": 2, "suspended": 1},
                      "player_seasons": 0, "transfers": 0}


def test_derives_fields_and_quality_metrics(tmp_path, raw_cache_dir, reference_db):
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    connection = sqlite3.connect(output)
    assert connection.execute("SELECT duration_days, age_at_start, is_ongoing FROM injury WHERE id = 900").fetchone() == (59, 25.1, 0)
    assert connection.execute("SELECT duration_days, is_ongoing FROM injury WHERE id = 902").fetchone() == (None, 1)
    metrics = dict(connection.execute("SELECT metric, value FROM data_quality"))
    assert {key: metrics[key] for key in ("raw_pivot_rows", "distinct_absences", "injuries", "category_suspended")} == {
        "raw_pivot_rows": 4.0, "distinct_absences": 3.0, "injuries": 2.0, "category_suspended": 1.0}


def test_stores_non_injury_absence_with_null_start_date(tmp_path, reference_db):
    """A suspension without a start_date must be retained, not abort the build.

    Injuries have start_date ~100% filled, but other categories don't — with
    every category now stored, a NOT NULL start_date would crash the ETL. This
    guards the nullable-start_date schema decision.
    """
    raw_dir = tmp_path / "fixtures"
    raw_dir.mkdir()
    (raw_dir / "10_2025-03.json").write_text(json.dumps({"league_id": 10, "fixtures": [
        {"id": 1, "season_id": 77, "sidelined": [
            {"id": 9990, "sideline_id": 999, "player_id": None, "type_id": None,
             "sideline": {"id": 999, "player_id": 5001, "type_id": 500, "category": "suspended",
                          "team_id": 100, "season_id": None, "start_date": None, "end_date": None,
                          "games_missed": None, "completed": False}},
        ]},
    ]}))

    result = etl.build(raw_dir, reference_db, tmp_path / "app.db")
    assert result == {"absences": 1, "injuries": 0, "categories": {"suspended": 1},
                      "player_seasons": 0, "transfers": 0}
    connection = sqlite3.connect(tmp_path / "app.db")
    assert connection.execute("SELECT start_date, is_ongoing FROM absence WHERE id = 999").fetchone() == (None, 1)


def test_extracts_player_season_stats(tmp_path, raw_cache_dir, reference_db):
    """Enriched player cache (statistics.details) becomes player_season rows."""
    players_dir = tmp_path / "players"
    players_dir.mkdir()
    (players_dir / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [{
            "player_id": 5001, "season_id": 77, "team_id": 100,
            "details": [
                {"type_id": etl.STAT_MINUTES, "value": {"total": 944}},
                {"type_id": etl.STAT_APPEARANCES, "value": {"total": 17}},
                {"type_id": etl.STAT_LINEUPS, "value": {"total": 11}},
                {"type_id": 99, "value": {"total": 3}},  # unrelated metric, ignored
            ],
        }],
    }))

    result = etl.build(raw_cache_dir, reference_db, tmp_path / "app.db", players_dir=players_dir)
    assert result["player_seasons"] == 1
    connection = sqlite3.connect(tmp_path / "app.db")
    assert connection.execute(
        "SELECT minutes_played, appearances, lineups FROM player_season "
        "WHERE player_id = 5001 AND season_id = 77").fetchone() == (944, 17, 11)


def test_extracts_transfers(tmp_path, raw_cache_dir, reference_db):
    """Enriched player cache (transfers include) becomes transfer rows, deduped by id."""
    players_dir = tmp_path / "players"
    players_dir.mkdir()
    (players_dir / "5001.json").write_text(json.dumps({
        "id": 5001,
        "transfers": [
            {"id": 700, "player_id": 5001, "from_team_id": 100, "to_team_id": 200,
             "date": "2022-07-01", "type_id": 219, "amount": 5000000,
             "completed": True, "career_ended": False},
            {"id": 700, "player_id": 5001, "from_team_id": 100, "to_team_id": 200,
             "date": "2022-07-01"},  # duplicate id — must collapse to one row
        ],
    }))

    result = etl.build(raw_cache_dir, reference_db, tmp_path / "app.db", players_dir=players_dir)
    assert result["transfers"] == 1
    connection = sqlite3.connect(tmp_path / "app.db")
    assert connection.execute(
        "SELECT from_team_id, to_team_id, amount, completed FROM transfer "
        "WHERE id = 700").fetchone() == (100, 200, 5000000, 1)
