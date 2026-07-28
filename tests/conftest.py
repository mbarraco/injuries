import base64
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import auth, db, etl

# Every route is behind HTTP Basic auth (app/main.py verify_auth). Credentials
# come from the environment, so tests set their own rather than depending on
# whatever the developer has in .env.
_USER, _PASSWORD = "tester", "testpass"
_AUTH_HEADER = "Basic " + base64.b64encode(f"{_USER}:{_PASSWORD}".encode()).decode()


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
    connection.execute("INSERT INTO sportmonks_team VALUES ('200', 'FC Rival', 'Testland', 1910, 'FCR')")
    connection.execute("INSERT INTO sportmonks_type VALUES ('500', 'Knock')")
    connection.execute("INSERT INTO sportmonks_season VALUES ('77', '10', 'Testland', 'Test League', '2024/2025', 1, '{}')")
    # A second, non-current season with a HIGHER id than the current one — this
    # is what makes MAX(season_id) the wrong squad-selection rule and
    # season.is_current the right one; the id order deliberately doesn't match
    # recency.
    connection.execute("INSERT INTO sportmonks_season VALUES ('78', '10', 'Testland', 'Test League', '2023/2024', 0, '{}')")
    connection.execute("INSERT INTO sportmonks_coverage VALUES (16, 'Testland', 'Test League', '10', '2024-08..2025-07', 500, 'moderate')")
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def players_dir(tmp_path):
    """Enriched player cache for player 5001: season minutes + one transfer.

    Backs the entity-page tests that need player_season/transfer rows (squad,
    season pages, player minutes/transfer history) — the base raw_cache_dir /
    reference_db fixtures don't populate either table.
    """
    directory = tmp_path / "players"
    directory.mkdir()
    (directory / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [{
            "player_id": 5001, "season_id": 77, "team_id": 100,
            "details": [
                {"type_id": 119, "value": {"total": 944}},
                {"type_id": 321, "value": {"total": 17}},
                {"type_id": 322, "value": {"total": 11}},
            ],
        }],
        # One of each state the UI must distinguish: a paid transfer, a free
        # transfer (no fee BY DEFINITION, not missing), a loan with no fee
        # disclosed, and a type absent from the vendor's taxonomy.
        "transfers": [
            {"id": 700, "player_id": 5001, "from_team_id": 200, "to_team_id": 100,
             "date": "2022-07-01", "type_id": 219, "amount": 5000000,
             "completed": True, "career_ended": False},
            {"id": 701, "player_id": 5001, "from_team_id": 100, "to_team_id": 200,
             "date": "2021-07-01", "type_id": 220, "amount": None,
             "completed": True, "career_ended": False},
            {"id": 702, "player_id": 5001, "from_team_id": 200, "to_team_id": 100,
             "date": "2020-07-01", "type_id": 218, "amount": None,
             "completed": True, "career_ended": False},
            {"id": 703, "player_id": 5001, "from_team_id": 100, "to_team_id": 200,
             "date": "2019-07-01", "type_id": 9688, "amount": None,
             "completed": True, "career_ended": False},
        ],
    }))
    # Player 5003 only ever played in the non-current season 78, at the same
    # team — this is the row that must NOT appear in team 100's current squad.
    (directory / "5003.json").write_text(json.dumps({
        "id": 5003,
        "statistics": [{
            "player_id": 5003, "season_id": 78, "team_id": 100,
            "details": [{"type_id": 119, "value": {"total": 500}}],
        }],
    }))
    return directory


@pytest.fixture
def rates_players_dir(tmp_path):
    """Playing time shaped around the two traps in the rate metric.

    Player 5003 moved mid-season: TWO player_season rows for season 77, at two
    different clubs (300 + 400 minutes). player_season is keyed
    (player, season, team), so a naive join to `absence` returns one row per
    club and divides the season's injuries by a single club's minutes — wrong,
    silently. The intended grain is (player, season): 700 minutes, one injury.

    Player 5001 sits at 90 minutes with one injury, which reads as 11.11 per
    1000 minutes. That is the artefact MINUTES_FLOOR exists to keep out of a
    ranking, so the floor is genuinely exercised rather than vacuously true.
    """
    directory = tmp_path / "rate_players"
    directory.mkdir()
    (directory / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [{"player_id": 5001, "season_id": 77, "team_id": 100,
                        "details": [{"type_id": 119, "value": {"total": 90}}]}],
    }))
    (directory / "5003.json").write_text(json.dumps({
        "id": 5003,
        "statistics": [
            {"player_id": 5003, "season_id": 77, "team_id": 100,
             "details": [{"type_id": 119, "value": {"total": 300}}]},
            {"player_id": 5003, "season_id": 77, "team_id": 200,
             "details": [{"type_id": 119, "value": {"total": 400}}]},
        ],
    }))
    return directory


@pytest.fixture
def types_file(tmp_path):
    """The vendor type taxonomy, as its own fixture.

    etl.build defaults this to the real data/raw cache; passing an explicit
    file keeps tests from silently depending on repo data that ingest runs
    change. Deliberately includes the transfer types (which coverage.db never
    holds, since resolve.py only stores absence-referenced ids) and omits 9688,
    so the unnamed-type path stays exercised.
    """
    path = tmp_path / "types.json"
    path.write_text(json.dumps([
        {"id": 218, "name": "Loan"},
        {"id": 219, "name": "Transfer"},
        {"id": 220, "name": "Free Transfer"},
    ]))
    return path


@pytest.fixture
def seasons_dir(tmp_path):
    """The cached league+seasons files, the wider source for both dimensions.

    Deliberately includes a competition that is ABSENT from reference_db —
    league 2, a cup. coverage.db only ever held the domestic leagues, so a
    fixture built from it alone would let the broken build pass: the cup is the
    whole gap the repair closes.
    """
    directory = tmp_path / "seasons"
    directory.mkdir()
    (directory / "10.json").write_text(json.dumps({
        # country_id 999 is fictional on purpose. The other fixtures already
        # call this country "Testland", and borrowing a real id (320 is Denmark)
        # would quietly attach an invented name to a real entity.
        "id": 10, "name": "Test League", "country_id": 999,
        "seasons": [
            {"id": 77, "league_id": 10, "name": "2024/2025", "is_current": True,
             "starting_at": "2024-08-16", "ending_at": "2025-05-31"},
            {"id": 78, "league_id": 10, "name": "2023/2024", "is_current": False,
             "starting_at": "2023-08-11", "ending_at": "2024-05-19"},
        ],
    }))
    # A real competition with its real values, so the cup path is exercised
    # against data that matches production rather than invented figures.
    (directory / "2.json").write_text(json.dumps({
        "id": 2, "name": "Champions League", "country_id": 41,
        "seasons": [
            {"id": 23619, "league_id": 2, "name": "2024/2025", "is_current": False,
             "starting_at": "2024-07-09", "ending_at": "2025-05-31"},
        ],
    }))
    # The vendor returns an empty document for a league whose seasons were never
    # cached; the real cache holds two of these. It must be skipped, not crash.
    (directory / "316.json").write_text(json.dumps({}))
    return directory


@pytest.fixture
def countries_file(tmp_path):
    """id -> name for the country the season files reference by id only.

    Real ids keep real names (41 is Europe, which is what the cups resolve to);
    the fictional league's country keeps a fictional id.
    """
    path = tmp_path / "countries.json"
    path.write_text(json.dumps([
        {"id": 999, "name": "Testland"},
        {"id": 41, "name": "Europe"},
    ]))
    return path


@pytest.fixture
def rates_connection(tmp_path, raw_cache_dir, reference_db, rates_players_dir, types_file,
                     seasons_dir, countries_file):
    """A database built from rates_players_dir — kept separate from `connection`
    so the mid-season-move rows don't perturb the squad and minutes assertions
    the entity-page tests make against the standard fixture."""
    output = tmp_path / "rates.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=rates_players_dir,
              types_file=types_file, seasons_dir=seasons_dir, countries_file=countries_file)
    return db.connect(output)


@pytest.fixture
def connection(tmp_path, raw_cache_dir, reference_db, players_dir, types_file,
               seasons_dir, countries_file):
    """A built app.db, opened read-only, for testing query functions directly.

    Cheaper and more precise than going through the HTTP client when the
    assertion is about returned data rather than rendered markup.
    """
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=players_dir,
              types_file=types_file, seasons_dir=seasons_dir, countries_file=countries_file)
    return db.connect(output)


@pytest.fixture
def client(tmp_path, raw_cache_dir, reference_db, players_dir, types_file,
           seasons_dir, countries_file, monkeypatch):
    monkeypatch.setenv(auth.USER_VAR, _USER)
    monkeypatch.setenv(auth.PASSWORD_VAR, _PASSWORD)
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=players_dir,
              types_file=types_file, seasons_dir=seasons_dir, countries_file=countries_file)
    monkeypatch.setattr("app.db.DB_PATH", str(output))
    from app.main import app
    return TestClient(app, headers={"Authorization": _AUTH_HEADER})


@pytest.fixture
def rates_client(tmp_path, raw_cache_dir, reference_db, rates_players_dir, types_file,
                 seasons_dir, countries_file, monkeypatch):
    """HTTP client over the rates fixture, where team 100's players (90 and 300
    minutes) both sit BELOW the floor — the "season is young" empty state that
    the standard fixture can't produce, since its player clears 450."""
    monkeypatch.setenv(auth.USER_VAR, _USER)
    monkeypatch.setenv(auth.PASSWORD_VAR, _PASSWORD)
    output = tmp_path / "rates_app.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=rates_players_dir,
              types_file=types_file, seasons_dir=seasons_dir, countries_file=countries_file)
    monkeypatch.setattr("app.db.DB_PATH", str(output))
    from app.main import app
    return TestClient(app, headers={"Authorization": _AUTH_HEADER})


@pytest.fixture
def multi_competition_connection(tmp_path, raw_cache_dir, reference_db, countries_file):
    """A club that is current in TWO competitions at the same time.

    Real clubs play their domestic league and, if they qualified, a UEFA
    competition — both seasons flagged is_current. This was impossible to
    represent before the cups reached the season dimension, which is why an
    ungrouped squad query listed a player once per competition and went
    unnoticed. Player 5001 has 944 minutes in the league and 200 in the cup at
    the same club: one player, one squad row, 1144 minutes.

    Kept separate from `connection` so the extra current season doesn't
    perturb assertions the other entity tests make about a single season.
    """
    seasons = tmp_path / "mc_seasons"
    seasons.mkdir()
    (seasons / "10.json").write_text(json.dumps({
        "id": 10, "name": "Test League", "country_id": 999,
        "seasons": [{"id": 77, "league_id": 10, "name": "2024/2025", "is_current": True,
                     "starting_at": "2024-08-16", "ending_at": "2025-05-31"}],
    }))
    (seasons / "2.json").write_text(json.dumps({
        "id": 2, "name": "Champions League", "country_id": 41,
        "seasons": [{"id": 23619, "league_id": 2, "name": "2024/2025", "is_current": True,
                     "starting_at": "2024-07-09", "ending_at": "2025-05-31"}],
    }))

    players = tmp_path / "mc_players"
    players.mkdir()
    (players / "5001.json").write_text(json.dumps({
        "id": 5001,
        "statistics": [
            {"player_id": 5001, "season_id": 77, "team_id": 100,
             "details": [{"type_id": 119, "value": {"total": 944}}]},
            {"player_id": 5001, "season_id": 23619, "team_id": 100,
             "details": [{"type_id": 119, "value": {"total": 200}}]},
        ],
    }))

    output = tmp_path / "mc.db"
    etl.build(raw_cache_dir, reference_db, output, players_dir=players,
              seasons_dir=seasons, countries_file=countries_file)
    return db.connect(output)
