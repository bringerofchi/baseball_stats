-- MLB Edge Lab — Core Schema
-- SQLite dialect (portable to Postgres with minor type tweaks: TEXT->VARCHAR, INTEGER PK -> SERIAL, etc.)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- games: one row per scheduled/played game
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS games (
    game_id             TEXT PRIMARY KEY,       -- source game id (SportsDataIO GameID, stringified)
    date                TEXT NOT NULL,           -- ISO date, YYYY-MM-DD
    home_team           TEXT NOT NULL,
    away_team           TEXT NOT NULL,
    stadium             TEXT,
    weather_temp        REAL,
    weather_wind_speed  REAL,
    weather_wind_direction TEXT,
    weather_precipitation REAL,
    status              TEXT DEFAULT 'scheduled',  -- scheduled|in_progress|final|postponed
    inserted_at         TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games(date);

-- ---------------------------------------------------------------------
-- odds: one row per (game, sportsbook). Multiple sportsbooks per game.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS odds (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id                     TEXT NOT NULL REFERENCES games(game_id),
    sportsbook                  TEXT NOT NULL,
    opening_moneyline_home      INTEGER,
    opening_moneyline_away      INTEGER,
    closing_moneyline_home      INTEGER,
    closing_moneyline_away      INTEGER,
    opening_runline_home        REAL,
    opening_runline_home_price  INTEGER,
    opening_runline_away        REAL,
    opening_runline_away_price  INTEGER,
    closing_runline_home        REAL,
    closing_runline_home_price  INTEGER,
    closing_runline_away        REAL,
    closing_runline_away_price  INTEGER,
    opening_total                REAL,
    opening_total_over_price     INTEGER,
    opening_total_under_price    INTEGER,
    closing_total                REAL,
    closing_total_over_price     INTEGER,
    closing_total_under_price    INTEGER,
    captured_at                 TEXT DEFAULT (datetime('now')),
    UNIQUE(game_id, sportsbook)
);

CREATE INDEX IF NOT EXISTS idx_odds_game ON odds(game_id);

-- ---------------------------------------------------------------------
-- starters: starting pitcher info per game
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS starters (
    game_id                     TEXT PRIMARY KEY REFERENCES games(game_id),
    home_pitcher_name           TEXT,
    away_pitcher_name           TEXT,
    home_ERA                    REAL,
    away_ERA                    REAL,
    home_xERA                   REAL,
    away_xERA                   REAL,
    home_days_rest              INTEGER,
    away_days_rest              INTEGER,
    pitch_count_last_start_home INTEGER,
    pitch_count_last_start_away INTEGER
);

-- ---------------------------------------------------------------------
-- team_form: rolling form metrics, one row per (team, date)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_form (
    team                            TEXT NOT NULL,
    date                            TEXT NOT NULL,
    last_5_runs_scored_avg          REAL,
    last_5_runs_allowed_avg         REAL,
    bullpen_innings_last_3_days     REAL,
    win_streak                      INTEGER DEFAULT 0,
    loss_streak                     INTEGER DEFAULT 0,
    last_game_margin                INTEGER,   -- signed: + = won by N, - = lost by N (for overreaction edge)
    extra_innings_last_game         INTEGER DEFAULT 0,
    PRIMARY KEY (team, date)
);

-- ---------------------------------------------------------------------
-- outcomes: final results, one row per game
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    game_id         TEXT PRIMARY KEY REFERENCES games(game_id),
    final_score_home INTEGER,
    final_score_away INTEGER,
    winner           TEXT,           -- 'home' | 'away'
    total_runs       INTEGER,
    innings_played   INTEGER DEFAULT 9
);

-- ---------------------------------------------------------------------
-- edges: computed signal outputs per game (wide table, one row per game)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edges (
    game_id                 TEXT PRIMARY KEY REFERENCES games(game_id),
    sp_edge_score           REAL,     -- Edge 1: starting pitcher mismatch
    sp_model_implied_prob_home REAL,
    sp_market_implied_prob_home REAL,
    bullpen_fatigue_index_home REAL,  -- Edge 2
    bullpen_fatigue_index_away REAL,
    overreaction_flag       INTEGER DEFAULT 0,  -- Edge 3, boolean 0/1
    overreaction_direction  TEXT,     -- 'home_faded' | 'away_faded' | NULL
    computed_at             TEXT DEFAULT (datetime('now')),
    -- Provenance columns, matching odds/starters, stamped by the
    -- orchestrator's compute_edges stage handler (see stage_registry.py).
    -- See migrate_add_edges_provenance.sql for adding these to an
    -- existing DB that predates this convention on the edges table.
    data_source              TEXT,
    timestamp_collected      TEXT,
    collection_stage         TEXT,
    data_version             TEXT,
    collection_status        TEXT
);

-- ---------------------------------------------------------------------
-- edge_results: post-game ROI/CLV/hit-rate ledger, one row per (game, edge_type, sportsbook)
-- This is the table long-run statistical testing queries hit.
--
-- UNIQUE(game_id, edge_type, sportsbook) makes logging idempotent: running
-- Settle more than once for the same date (e.g. once mid-day to catch
-- early finishers, again later for the rest) re-evaluates and updates the
-- existing row instead of inserting a duplicate. Without this, N in every
-- downstream ROI/hit-rate query silently inflates by however many times
-- Settle was re-run — a real bug found and fixed after exactly that
-- discrepancy showed up between the summary report and independently
-- re-derived research-tool numbers.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edge_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    edge_type           TEXT NOT NULL,   -- 'sp_mismatch' | 'bullpen_fatigue' | 'overreaction'
    side_taken          TEXT,            -- 'home' | 'away' | 'over' | 'under'
    sportsbook          TEXT,
    stake               REAL DEFAULT 1.0,        -- unit stake (flat 1u by default)
    odds_taken          INTEGER,                 -- american odds at time of "bet"
    closing_odds        INTEGER,                 -- closing line for CLV calc
    clv_pct             REAL,                     -- closing line value, %
    result              TEXT,            -- 'win' | 'loss' | 'push' | 'pending'
    profit_units        REAL,
    signal_value         REAL,           -- the raw edge metric value at bet time (e.g. xERA gap)
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(game_id, edge_type, sportsbook)
);

CREATE INDEX IF NOT EXISTS idx_edge_results_type ON edge_results(edge_type);
CREATE INDEX IF NOT EXISTS idx_edge_results_game ON edge_results(game_id);
