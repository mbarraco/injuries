-- app.db is derived from the cache by etl.py and is never hand-edited.

DROP VIEW  IF EXISTS injury;
DROP TABLE IF EXISTS absence;
DROP TABLE IF EXISTS player;
DROP TABLE IF EXISTS player_season;
DROP TABLE IF EXISTS transfer;
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

-- Per-player, per-season playing time, extracted from the enriched player
-- cache (statistics.details). minutes_played is the denominator that turns
-- raw injury counts into an injury *rate*. Empty until the player enrichment
-- pass has run; players still on the thin fetch contribute no rows.
CREATE TABLE player_season (
    player_id INTEGER REFERENCES player(id),
    season_id INTEGER REFERENCES season(id),
    team_id INTEGER REFERENCES team(id),
    minutes_played INTEGER,
    appearances INTEGER,
    lineups INTEGER,
    PRIMARY KEY (player_id, season_id, team_id)
);

CREATE INDEX idx_player_season_player ON player_season(player_id);

-- Career transfers, extracted from the enriched player cache. from_/to_team
-- are deliberately NOT foreign keys: a move often involves a club outside our
-- 53-league team dimension (lower divisions, other confederations), and we
-- want to keep those rows rather than drop them.
CREATE TABLE transfer (
    id INTEGER PRIMARY KEY,
    player_id INTEGER REFERENCES player(id),
    from_team_id INTEGER,
    to_team_id INTEGER,
    date TEXT,
    type_id INTEGER,
    amount INTEGER,
    completed INTEGER,
    career_ended INTEGER
);

CREATE INDEX idx_transfer_player ON transfer(player_id);

-- Every sidelined absence, regardless of category. Nothing is dropped at
-- ingest time: injuries, suspensions and uncategorised rows all land here
-- with their raw `category`, so the full picture stays queryable.
CREATE TABLE absence (
    id INTEGER PRIMARY KEY,
    player_id INTEGER REFERENCES player(id),
    team_id INTEGER REFERENCES team(id),
    league_id INTEGER REFERENCES league(id),
    season_id INTEGER REFERENCES season(id),
    type_id INTEGER REFERENCES injury_type(id),
    category TEXT,
    -- Nullable: unlike injuries (start_date ~100% filled), some suspension /
    -- uncategorised absences arrive without one. The injury view the app reads
    -- only exposes injury-category rows, so this never surfaces a null there.
    start_date TEXT,
    end_date TEXT,
    games_missed INTEGER,
    completed INTEGER,
    fixture_appearances INTEGER NOT NULL,
    duration_days INTEGER,
    age_at_start REAL,
    is_ongoing INTEGER NOT NULL
);

CREATE INDEX idx_absence_league ON absence(league_id);
CREATE INDEX idx_absence_season ON absence(season_id);
CREATE INDEX idx_absence_player ON absence(player_id);
CREATE INDEX idx_absence_type ON absence(type_id);
CREATE INDEX idx_absence_start ON absence(start_date);
CREATE INDEX idx_absence_category ON absence(category);

-- The app is an injury database: this view is what the query layer reads, so
-- existing injury-centric queries keep working unchanged while the base table
-- retains suspensions and everything else for anyone who wants them.
CREATE VIEW injury AS SELECT * FROM absence WHERE category = 'injury';

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
