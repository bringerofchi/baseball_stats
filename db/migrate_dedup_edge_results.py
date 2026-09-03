"""
One-time migration: deduplicates edge_results (in case Settle was ever
re-run for the same date before the UNIQUE(game_id, edge_type, sportsbook)
constraint existed) and rebuilds the table with that constraint in place.

SQLite can't add a constraint to an existing table via ALTER TABLE, so this
does the standard SQLite migration dance: build a new table with the right
schema, copy deduplicated data into it, drop the old table, rename the new
one. Runs against whichever database config.DB_PATH currently points to.

Safe to run multiple times — if the constraint is already in place, this
is a no-op (detected before doing anything).

Usage:
    python -m db.migrate_dedup_edge_results
"""
import sys

sys.path.append(".")

from db.database import connection


def _constraint_already_present(conn) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='edge_results'"
    ).fetchone()
    if not row or not row["sql"]:
        return False
    return "UNIQUE" in row["sql"].upper() and "GAME_ID" in row["sql"].upper()


def migrate():
    with connection() as conn:
        if _constraint_already_present(conn):
            print("[migrate] edge_results already has the UNIQUE constraint — nothing to do.")
            return

        before_count = conn.execute("SELECT COUNT(*) as c FROM edge_results").fetchone()["c"]

        # Keep the most recent row per (game_id, edge_type, sportsbook) —
        # "most recent" as a reasonable tiebreak, since duplicates should
        # be identical or near-identical anyway (same game, same edge,
        # re-evaluated).
        conn.executescript("""
            CREATE TABLE edge_results_new (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id             TEXT NOT NULL REFERENCES games(game_id),
                edge_type           TEXT NOT NULL,
                side_taken          TEXT,
                sportsbook          TEXT,
                stake               REAL DEFAULT 1.0,
                odds_taken          INTEGER,
                closing_odds        INTEGER,
                clv_pct             REAL,
                result              TEXT,
                profit_units        REAL,
                signal_value         REAL,
                created_at          TEXT DEFAULT (datetime('now')),
                UNIQUE(game_id, edge_type, sportsbook)
            );

            INSERT INTO edge_results_new
                (game_id, edge_type, side_taken, sportsbook, stake, odds_taken,
                 closing_odds, clv_pct, result, profit_units, signal_value, created_at)
            SELECT game_id, edge_type, side_taken, sportsbook, stake, odds_taken,
                   closing_odds, clv_pct, result, profit_units, signal_value, created_at
            FROM edge_results
            WHERE id IN (
                SELECT MAX(id) FROM edge_results
                GROUP BY game_id, edge_type, sportsbook
            );

            DROP TABLE edge_results;
            ALTER TABLE edge_results_new RENAME TO edge_results;

            CREATE INDEX IF NOT EXISTS idx_edge_results_type ON edge_results(edge_type);
            CREATE INDEX IF NOT EXISTS idx_edge_results_game ON edge_results(game_id);
        """)

        after_count = conn.execute("SELECT COUNT(*) as c FROM edge_results").fetchone()["c"]
        removed = before_count - after_count
        print(f"[migrate] edge_results: {before_count} rows before, {after_count} after "
              f"({removed} duplicate row(s) removed). UNIQUE constraint now in place.")


if __name__ == "__main__":
    migrate()
