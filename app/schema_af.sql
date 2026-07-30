-- apifootball.db is derived from data/raw/apifootball/ by etl_af.py and is
-- never hand-edited.
--
-- Deliberately NOT a copy of schema.sql. The two vendors differ structurally,
-- and mirroring column names would put measured Sportmonks values and inferred
-- API-Football ones side by side under identical headings, with no way for a
-- reader to tell them apart. Every divergence below is a measured fact from
-- logbook/apifootball.md, not a style choice:
--
--   * NO spell id exists. The vendor's grain is one row per (player, fixture)
--     -- "this player missed this match". A multi-match absence is N rows.
--   * NO start_date / end_date / games_missed / completed. Those are Sportmonks
--     fields. Reconstructing them here means inferring, and the inference moves
--     75% across plausible thresholds, so it is a labelled view, never a column.
--   * `type` is new and load-bearing: 13% of rows are "Questionable" (a doubt
--     about availability), not "Missing Fixture" (a confirmed absence). Summing
--     them overstates absences by ~13%.
--   * `reason` is free text with 205 distinct values mixing injuries with
--     suspensions and administrative absences -- not a type FK.

DROP VIEW  IF EXISTS af_unmapped_reason;
DROP VIEW  IF EXISTS af_injury;
DROP VIEW  IF EXISTS af_confirmed_absence;
DROP TABLE IF EXISTS af_absence;
DROP TABLE IF EXISTS af_player_season;
DROP TABLE IF EXISTS af_fixture;
DROP TABLE IF EXISTS af_player;
DROP TABLE IF EXISTS af_team;
DROP TABLE IF EXISTS af_league_season;
DROP TABLE IF EXISTS af_league;
DROP TABLE IF EXISTS af_reason;
DROP TABLE IF EXISTS af_data_quality;
DROP TABLE IF EXISTS af_ingest_run;

CREATE TABLE af_league (
    id      INTEGER PRIMARY KEY,
    name    TEXT,
    country TEXT           -- "World" for UCL/UEL/UECL/Super Cup, not a nation
);

CREATE INDEX idx_af_league_name ON af_league(name COLLATE NOCASE);

-- API-Football has no season entity: a season is an integer year scoped to a
-- league (2020 = 2020/21 for autumn-spring leagues, the calendar year for
-- Nordic/Russian ones). So this is a link table, not a dimension with its own
-- surrogate id -- inventing one would imply a vendor concept that isn't there.
CREATE TABLE af_league_season (
    league_id      INTEGER REFERENCES af_league(id),
    season         INTEGER NOT NULL,
    has_injuries   INTEGER NOT NULL,   -- the vendor's coverage.injuries flag
    PRIMARY KEY (league_id, season)
);

CREATE TABLE af_team (
    id             INTEGER PRIMARY KEY,
    name           TEXT,
    country        TEXT,
    founded        INTEGER,            -- 95.5% populated
    code           TEXT,               -- 89.3%
    venue_id       INTEGER,
    venue_name     TEXT,
    venue_city     TEXT,
    venue_capacity INTEGER
);

CREATE INDEX idx_af_team_name ON af_team(name COLLATE NOCASE);

-- Fill rates measured 2026-07-29 over a 2,000-record sample. height/weight are
-- kept despite being sparse because they are cheap and occasionally useful;
-- any query using them must state the coverage rather than imply completeness.
CREATE TABLE af_player (
    id            INTEGER PRIMARY KEY,
    name          TEXT,                -- 100%, abbreviated ("D. Costa")
    firstname     TEXT,                -- 100%
    lastname      TEXT,                -- 100%
    birth_date    TEXT,                -- 100% -- age analysis IS possible
    birth_country TEXT,                -- 100%
    nationality   TEXT,                -- 100%
    height_cm     INTEGER,             -- 70.0%  <- sparse
    weight_kg     INTEGER              -- 57.9%  <- sparse
);

CREATE INDEX idx_af_player_name ON af_player(name COLLATE NOCASE);

-- The rate denominator, and the correction to an earlier assumption: minutes
-- come from the ALREADY-CACHED /players endpoint (statistics[].games.minutes,
-- 89.3% populated), not from the 32,000-call /fixtures/players crawl. Rates are
-- buildable without it; that crawl buys per-match granularity, not rates.
--
-- `position` is season-scoped, not a player attribute: the vendor reports it
-- per (player, league, season) via statistics[].games.position, which is more
-- honest than a single career position since players move.
CREATE TABLE af_player_season (
    player_id    INTEGER REFERENCES af_player(id),
    league_id    INTEGER REFERENCES af_league(id),
    season       INTEGER NOT NULL,
    team_id      INTEGER REFERENCES af_team(id),
    position     TEXT,                 -- 100% where a statistics row exists
    appearances  INTEGER,              -- 89.3%
    lineups      INTEGER,              -- 89.3%
    minutes      INTEGER,              -- 89.3%  <- THE DENOMINATOR
    rating       REAL,                 -- 66.6%  <- sparse
    PRIMARY KEY (player_id, league_id, season, team_id)
);

CREATE INDEX idx_af_ps_player ON af_player_season(player_id);
CREATE INDEX idx_af_ps_season ON af_player_season(league_id, season);
CREATE INDEX idx_af_ps_team   ON af_player_season(team_id);

-- Every match, whether or not anyone was absent from it. Needed as the
-- denominator for "share of fixtures with an absence" and to give each absence
-- row a real date. 81.8% carry goals -- the remainder are future fixtures in
-- the current season, not missing data.
CREATE TABLE af_fixture (
    id           INTEGER PRIMARY KEY,
    league_id    INTEGER REFERENCES af_league(id),
    season       INTEGER NOT NULL,
    date         TEXT,                 -- ISO 8601 with offset
    timestamp    INTEGER,
    status_short TEXT,                 -- FT, NS, PST, ...
    round        TEXT,
    venue_name   TEXT,
    referee      TEXT,                 -- 81.8%
    home_team_id INTEGER REFERENCES af_team(id),
    away_team_id INTEGER REFERENCES af_team(id),
    goals_home   INTEGER,
    goals_away   INTEGER
);

CREATE INDEX idx_af_fixture_league ON af_fixture(league_id, season);
CREATE INDEX idx_af_fixture_date   ON af_fixture(date);

-- Normalisation of the 205 distinct free-text `reason` values. A mapping table
-- rather than a hardcoded CASE so the classification is inspectable, testable
-- and correctable without touching queries -- and so "how many are injuries?"
-- has an auditable answer rather than a buried regex.
--
-- `category`: injury | suspension | administrative | unknown
--
-- INVARIANT the ETL must uphold: every distinct `reason` string present in
-- af_absence has a row here, categorising it as 'unknown' if nothing else
-- matches. This is NOT optional bookkeeping -- af_injury joins this table, so
-- a reason with no row here does not become 'unknown', it vanishes from the
-- view entirely and under-reports injuries with no error. The
-- af_unmapped_reason view below exists to make any such gap visible, and
-- af_data_quality carries the count so a rebuild can assert it is zero.
--
-- Matching is exact and case-sensitive (SQLite TEXT default collation), so the
-- ETL must store the vendor string VERBATIM on both sides. Normalising case or
-- whitespace in one place and not the other silently breaks the join.
CREATE TABLE af_reason (
    reason     TEXT PRIMARY KEY,       -- the raw vendor string, verbatim
    category   TEXT NOT NULL,
    body_part  TEXT,                   -- 'knee', 'ankle', ... where derivable
    row_count  INTEGER                 -- occurrences, for auditing the mapping
);

-- THE CORE TABLE. Grain: one row per (player, fixture) absence record, exactly
-- as the vendor supplies it. A surrogate key rather than a natural one because
-- a player can legitimately hold more than one row for a fixture (e.g. a
-- doubt logged separately from a confirmed absence).
--
-- Note there is no season_id FK: season is an integer scoped by league, and is
-- denormalised here so absence queries never need a join to filter by it.
CREATE TABLE af_absence (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER REFERENCES af_player(id),
    fixture_id INTEGER REFERENCES af_fixture(id),
    team_id    INTEGER REFERENCES af_team(id),
    league_id  INTEGER REFERENCES af_league(id),
    season     INTEGER NOT NULL,
    -- 'Missing Fixture' (87.0%) or 'Questionable' (13.0%). NEVER sum across
    -- these: one is a confirmed absence, the other is a doubt that may not
    -- have materialised.
    type       TEXT NOT NULL,
    reason     TEXT REFERENCES af_reason(reason),
    fixture_date TEXT                  -- denormalised from af_fixture
);

CREATE INDEX idx_af_absence_player  ON af_absence(player_id);
CREATE INDEX idx_af_absence_fixture ON af_absence(fixture_id);
CREATE INDEX idx_af_absence_league  ON af_absence(league_id, season);
CREATE INDEX idx_af_absence_team    ON af_absence(team_id);
CREATE INDEX idx_af_absence_type    ON af_absence(type);
CREATE INDEX idx_af_absence_reason  ON af_absence(reason);
CREATE INDEX idx_af_absence_date    ON af_absence(fixture_date);

-- Confirmed absences only -- excludes the 13% of rows that record a doubt.
-- Most queries should read this rather than af_absence.
CREATE VIEW af_confirmed_absence AS
    SELECT * FROM af_absence WHERE type = 'Missing Fixture';

-- The injury-only view, mirroring the `injury` view in schema.sql so the two
-- apps read structurally similar things -- but note this is a view over
-- FIXTURE APPEARANCES, not over spells. One injury spanning 8 matches is 8
-- rows here, whereas one row in Sportmonks' `injury` view is one whole spell.
-- The two are NOT comparable by row count.
--
-- LEFT JOIN, not INNER: with an inner join an absence whose reason is missing
-- from af_reason is dropped before the WHERE clause ever sees it, so a mapping
-- gap looks identical to "there were no injuries". The left join keeps the row
-- in the join result; the explicit category test then excludes it, but
-- af_unmapped_reason still reports it. Same end result, detectable failure.
CREATE VIEW af_injury AS
    SELECT a.* FROM af_absence a
    LEFT JOIN af_reason r ON r.reason = a.reason
    WHERE a.type = 'Missing Fixture' AND r.category = 'injury';

-- Any absence reason with no row in af_reason. MUST be empty after a rebuild.
-- Non-empty means af_injury is silently under-reporting by exactly these rows.
CREATE VIEW af_unmapped_reason AS
    SELECT a.reason, COUNT(*) AS rows_affected
    FROM af_absence a
    LEFT JOIN af_reason r ON r.reason = a.reason
    WHERE r.reason IS NULL
    GROUP BY a.reason
    ORDER BY rows_affected DESC;

CREATE TABLE af_data_quality (
    metric TEXT PRIMARY KEY,
    value  REAL,
    detail TEXT
);

CREATE TABLE af_ingest_run (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at    TEXT NOT NULL,
    source_file_count INTEGER,
    notes     TEXT
);
