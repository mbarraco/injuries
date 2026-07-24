import json
import sqlite3

import pytest


@pytest.fixture
def raw_cache_dir(tmp_path):
    directory = tmp_path / "fixtures"
    directory.mkdir()

    def sidelined(sideline_id, player_id, category, start, end, games_missed=3):
        return {"id": sideline_id * 10, "sideline_id": sideline_id, "player_id": None, "type_id": None,
                "sideline": {"id": sideline_id, "player_id": player_id, "type_id": 500,
                             "category": category, "team_id": 100, "season_id": None,
                             "start_date": start, "end_date": end, "games_missed": games_missed,
                             "completed": end is not None}}

    (directory / "10_2025-03.json").write_text(json.dumps({"league_id": 10, "fixtures": [
        {"id": 1, "season_id": 77, "sidelined": [
            sidelined(900, 5001, "injury", "2025-02-01", "2025-04-01"),
            sidelined(901, 5002, "suspended", "2025-03-01", "2025-03-20"),
        ]},
        {"id": 2, "season_id": 77, "sidelined": [
            sidelined(900, 5001, "injury", "2025-02-01", "2025-04-01"),
            sidelined(902, 5003, "injury", "2025-03-05", None),
        ]},
    ]}))
    return directory


@pytest.fixture
def reference_db(tmp_path):
    path = tmp_path / "coverage.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE sportmonks_player (id TEXT PRIMARY KEY, name TEXT, position TEXT, detailed_position TEXT, nationality TEXT, date_of_birth TEXT, height_cm INTEGER, weight_kg INTEGER);
        CREATE TABLE sportmonks_team (id TEXT PRIMARY KEY, name TEXT, country TEXT, founded INTEGER, short_code TEXT);
        CREATE TABLE sportmonks_type (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE sportmonks_season (id TEXT PRIMARY KEY, league_id TEXT, country TEXT, league_name TEXT, name TEXT, is_current INTEGER, dates_json TEXT);
        CREATE TABLE sportmonks_coverage (run_id INTEGER, country TEXT, league TEXT, sportmonks_id TEXT, year_bucket TEXT, record_count INTEGER, tier TEXT);
    """)
    connection.execute("INSERT INTO sportmonks_player VALUES ('5001', 'A. Player', 'Defender', 'Centre Back', 'Brazil', '2000-01-01', 180, 75)")
    connection.execute("INSERT INTO sportmonks_player VALUES ('5003', 'C. Player', 'Forward', 'Striker', 'Spain', '1995-06-15', 175, 70)")
    connection.execute("INSERT INTO sportmonks_team VALUES ('100', 'FC Test', 'Testland', 1900, 'FCT')")
    connection.execute("INSERT INTO sportmonks_type VALUES ('500', 'Knock')")
    connection.execute("INSERT INTO sportmonks_season VALUES ('77', '10', 'Testland', 'Test League', '2024/2025', 1, '{}')")
    connection.execute("INSERT INTO sportmonks_coverage VALUES (16, 'Testland', 'Test League', '10', '2024-08..2025-07', 500, 'moderate')")
    connection.commit()
    connection.close()
    return path
