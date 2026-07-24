-- app.db is derived from the cache by etl.py and is never hand-edited.

DROP TABLE IF EXISTS injury;
DROP TABLE IF EXISTS player;
DROP TABLE IF EXISTS team;
DROP TABLE IF EXISTS injury_type;
DROP TABLE IF EXISTS season;
DROP TABLE IF EXISTS league;
DROP TABLE IF EXISTS league_coverage;
DROP TABLE IF EXISTS data_quality;
DROP TABLE IF EXISTS ingest_run;

CREATE TABLE league (
    id INTEGER PRIMARY KEY,
    country TEXT,
    name TEXT
);

CREATE TABLE season (
    id INTEGER PRIMARY KEY,
    league_id INTEGER REFERENCES league(id),
    name TEXT,
    is_current INTEGER
);

CREATE TABLE team (
    id INTEGER PRIMARY KEY,
    name TEXT,
    country TEXT,
    founded INTEGER,
    short_code TEXT
);

CREATE TABLE player (
    id INTEGER PRIMARY KEY,
    name TEXT,
    position TEXT,
    detailed_position TEXT,
    nationality TEXT,
    date_of_birth TEXT,
    height_cm INTEGER,
    weight_kg INTEGER
);

CREATE TABLE injury_type (
    id INTEGER PRIMARY KEY,
    name TEXT
);

CREATE TABLE injury (
    id INTEGER PRIMARY KEY,
    player_id INTEGER REFERENCES player(id),
    team_id INTEGER REFERENCES team(id),
    league_id INTEGER REFERENCES league(id),
    season_id INTEGER REFERENCES season(id),
    type_id INTEGER REFERENCES injury_type(id),
    start_date TEXT NOT NULL,
    end_date TEXT,
    games_missed INTEGER,
    completed INTEGER,
    fixture_appearances INTEGER NOT NULL,
    duration_days INTEGER,
    age_at_start REAL,
    is_ongoing INTEGER NOT NULL
);

CREATE INDEX idx_injury_league ON injury(league_id);
CREATE INDEX idx_injury_season ON injury(season_id);
CREATE INDEX idx_injury_player ON injury(player_id);
CREATE INDEX idx_injury_type ON injury(type_id);
CREATE INDEX idx_injury_start ON injury(start_date);

CREATE TABLE league_coverage (
    country TEXT,
    league TEXT,
    league_id INTEGER,
    year_bucket TEXT,
    record_count INTEGER,
    tier TEXT
);

CREATE TABLE data_quality (
    metric TEXT PRIMARY KEY,
    value REAL,
    detail TEXT
);

CREATE TABLE ingest_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    source_file_count INTEGER,
    notes TEXT
);
