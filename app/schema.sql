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
DROP TABLE IF EXISTS fixture_coverage;
DROP TABLE IF EXISTS data_quality;
DROP TABLE IF EXISTS ingest_run;

CREATE TABLE league (
    id INTEGER PRIMARY KEY,
    country TEXT,
    name TEXT
);

-- Prefix search (`name LIKE 'q%' COLLATE NOCASE`) needs a NOCASE index to use
-- an index range scan instead of a full table scan; a plain index can't serve
-- a case-insensitive LIKE.
CREATE INDEX idx_league_name ON league(name COLLATE NOCASE);

CREATE TABLE season (
    id INTEGER PRIMARY KEY,
    league_id INTEGER REFERENCES league(id),
    name TEXT,
    is_current INTEGER,
    -- The vendor's real window for the season. Kept because transfers carry a
    -- date but no season_id, so bucketing them means matching that date against
    -- an actual window rather than assuming a league calendar. Null for seasons
    -- that reached the dimension only via coverage.db, which doesn't store them.
    starting_at TEXT,
    ending_at TEXT
);

CREATE TABLE team (
    id INTEGER PRIMARY KEY,
    name TEXT,
    country TEXT,
    founded INTEGER,
    short_code TEXT
);

CREATE INDEX idx_team_name ON team(name COLLATE NOCASE);

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

CREATE INDEX idx_player_name ON player(name COLLATE NOCASE);

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
-- Season and team pages filter on these; without them each one table-scans
-- 44k rows.
CREATE INDEX idx_player_season_season ON player_season(season_id);
CREATE INDEX idx_player_season_team   ON player_season(team_id);

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
-- Team pages list transfers in and out, neither of which goes via player_id.
CREATE INDEX idx_transfer_from   ON transfer(from_team_id);
CREATE INDEX idx_transfer_to     ON transfer(to_team_id);

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
CREATE INDEX idx_absence_team ON absence(team_id);
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

-- Fixture counts per league-season, aggregated during the same cache scan
-- collect_absences already performs — fixtures live only in the raw cache
-- (9,866 files), never in app.db otherwise, and a second pass would double
-- the I/O for counts available almost for free.
-- season_id is deliberately NOT a foreign key: some cached fixtures reference
-- seasons outside the dimension, and dropping them would understate coverage,
-- which is the one error these tables must never make.
CREATE TABLE fixture_coverage (
    league_id        INTEGER REFERENCES league(id),
    season_id        INTEGER,
    fixtures         INTEGER NOT NULL,
    non_empty_months INTEGER NOT NULL,
    PRIMARY KEY (league_id, season_id)
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
