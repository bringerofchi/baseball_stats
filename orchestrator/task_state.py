"""
Orchestrator state tracking.

Owns two tables, logically separate from the existing MLB Edge Lab tables
(games, odds, starters, team_form, outcomes, edges, edge_results):

    orchestrator_runs     — current status per (game_id, stage_name).
                             This is the idempotency check: "has this
                             already run / does it need to run again?"
    orchestrator_run_log  — append-only audit trail, one row per attempt.
                             Answers "what happened, and when" without
                             needing to guess from the current-state row.

Also owns provenance columns added to the *existing* tables the ingest
pipeline writes to (games, odds, starters) — per the spec's instruction
not to create duplicate storage for provenance, it's added as columns on
the real rows rather than a separate collection_events table.
"""
import sqlite3
import time
from contextlib import contextmanager

import config

ORCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS orchestrator_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    stage_name      TEXT NOT NULL,
    scheduled_time  TEXT NOT NULL,
    execution_time  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
        -- pending | running | completed | failed | skipped
    attempt_number  INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(game_id, stage_name)
);

CREATE INDEX IF NOT EXISTS idx_orch_runs_status ON orchestrator_runs(status);

CREATE TABLE IF NOT EXISTS orchestrator_run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    stage_name      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    status          TEXT NOT NULL,
    error_message   TEXT,
    logged_at       TEXT DEFAULT (datetime('now'))
);
"""

# Provenance columns added to existing pipeline tables. Kept minimal and
# separate from each table's domain columns (e.g. games.status already
# means game state — collection_status is a distinct concept and gets its
# own name).
PROVENANCE_COLUMNS = {
    "games": [
        ("data_source", "TEXT"),
        ("timestamp_collected", "TEXT"),
        ("collection_stage", "TEXT"),
        ("data_version", "TEXT"),
        ("collection_status", "TEXT"),
        ("game_time_utc", "TEXT"),  # see ingest_games patch — required for game_offset scheduling
    ],
    "odds": [
        ("data_source", "TEXT"),
        ("timestamp_collected", "TEXT"),
        ("collection_stage", "TEXT"),
        ("data_version", "TEXT"),
        ("collection_status", "TEXT"),
    ],
    "starters": [
        ("data_source", "TEXT"),
        ("timestamp_collected", "TEXT"),
        ("collection_stage", "TEXT"),
        ("data_version", "TEXT"),
        ("collection_status", "TEXT"),
    ],
}

DATA_VERSION = "orch_v1"


def _existing_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_schema(conn):
    """Idempotent startup migration: create orchestrator tables and add
    any missing provenance columns to existing tables. Safe to call on
    every runner startup."""
    conn.executescript(ORCH_SCHEMA)

    for table, columns in PROVENANCE_COLUMNS.items():
        existing = _existing_columns(conn, table)
        for col_name, col_type in columns:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
    conn.commit()


def health_check(conn):
    """Startup validation per spec: db exists, WAL active, required
    tables exist. Raises RuntimeError with a clear message if anything
    is wrong — this belongs in startup, not buried in task execution."""
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if mode.lower() != "wal":
        raise RuntimeError(
            f"Expected WAL journal mode, got '{mode}'. Check that "
            f"db.database.get_connection() sets PRAGMA journal_mode=WAL."
        )

    required_tables = {
        "games", "odds", "starters", "team_form", "outcomes",
        "edges", "edge_results", "orchestrator_runs", "orchestrator_run_log",
    }
    existing_tables = {
        row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = required_tables - existing_tables
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    return True


def recover_stale_running(conn, logger=None):
    """Any orchestrator_runs row still marked 'running' at process
    startup is definitionally stale: only one orchestrator process
    exists, so if we're just starting up, nothing can actually still be
    executing. This most often means the previous process was killed
    (window closed, crash) mid-stage rather than shut down gracefully.
    Reset to 'pending' so the next poll cycle retries it instead of it
    being stuck 'in progress' forever. This is the Application Restart
    recovery case called out in the spec."""
    stale = conn.execute(
        "SELECT id, game_id, stage_name FROM orchestrator_runs WHERE status='running'"
    ).fetchall()
    if stale:
        conn.execute("UPDATE orchestrator_runs SET status='pending', updated_at=datetime('now') WHERE status='running'")
        conn.commit()
        for row in stale:
            msg = (f"[recovery] {row['stage_name']} for {row['game_id']} was stuck 'running' "
                   f"from a previous process (likely killed rather than shut down cleanly) "
                   f"— reset to 'pending', will retry next cycle.")
            if logger:
                logger.warning(msg)
            else:
                print(msg)
    return len(stale)


# ---------------------------------------------------------------------
# Retry helper: sqlite3 "database is locked" backoff per spec.
# ---------------------------------------------------------------------
_BACKOFF_SCHEDULE = [0, 0.25, 1, 2]  # wait before attempts 2,3,4,5 (attempt 1 = immediate)


def with_lock_retry(fn, *, logger=None, max_attempts=5):
    """Runs fn() with retry on 'database is locked'. fn takes no args
    (wrap with a lambda/partial). Raises the final exception if all
    attempts are exhausted — a lock event should never silently
    disappear."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
            last_exc = e
            if logger:
                logger.warning(f"[task_state] DB locked, attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                wait = _BACKOFF_SCHEDULE[min(attempt - 1, len(_BACKOFF_SCHEDULE) - 1)]
                time.sleep(wait)
    raise last_exc


# ---------------------------------------------------------------------
# Run state CRUD
# ---------------------------------------------------------------------
def get_run(conn, game_id, stage_name):
    return conn.execute(
        "SELECT * FROM orchestrator_runs WHERE game_id=? AND stage_name=?",
        (game_id, stage_name),
    ).fetchone()


def upsert_pending(conn, game_id, stage_name, scheduled_time):
    """Ensures a run row exists in 'pending' state for this
    (game_id, stage_name), without overwriting an existing row's status
    (idempotent — calling this repeatedly while a stage is still pending
    or already completed is a no-op on status)."""
    conn.execute(
        """
        INSERT INTO orchestrator_runs (game_id, stage_name, scheduled_time, status)
        VALUES (?, ?, ?, 'pending')
        ON CONFLICT(game_id, stage_name) DO NOTHING
        """,
        (game_id, stage_name, scheduled_time),
    )


def mark_running(conn, run_id, attempt_number):
    conn.execute(
        """UPDATE orchestrator_runs SET status='running', attempt_number=?,
           updated_at=datetime('now') WHERE id=?""",
        (attempt_number, run_id),
    )


def mark_completed(conn, run_id):
    conn.execute(
        """UPDATE orchestrator_runs SET status='completed',
           execution_time=datetime('now'), error_message=NULL,
           updated_at=datetime('now') WHERE id=?""",
        (run_id,),
    )


def mark_failed(conn, run_id, error_message, attempt_number, final=False):
    status = "failed" if final else "pending"  # non-final failure goes back to pending for the next poll cycle to retry
    conn.execute(
        """UPDATE orchestrator_runs SET status=?, attempt_number=?,
           error_message=?, updated_at=datetime('now') WHERE id=?""",
        (status, attempt_number, error_message, run_id),
    )


def log_attempt(conn, game_id, stage_name, attempt_number, status, error_message=None):
    conn.execute(
        """INSERT INTO orchestrator_run_log
           (game_id, stage_name, attempt_number, status, error_message)
           VALUES (?, ?, ?, ?, ?)""",
        (game_id, stage_name, attempt_number, status, error_message),
    )
