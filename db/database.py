"""
Database connection helpers for MLB Edge Lab.

Uses sqlite3 directly (no ORM) — the schema is simple enough that raw SQL
with parameterized queries is easier to audit and debug than an ORM layer.
Swappable to Postgres later by changing get_connection() and any
SQLite-specific SQL (datetime('now'), AUTOINCREMENT, etc.)
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    # WAL mode + busy_timeout: required now that two long-running processes
    # (Flask + the orchestrator) write to this file concurrently. Must be
    # set on every connection, not just the one that first creates the
    # file — journal_mode is persistent once set, but busy_timeout is a
    # per-connection setting and needs to be re-applied here every time.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextmanager
def connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't already exist."""
    schema_sql = SCHEMA_PATH.read_text()
    with connection() as conn:
        conn.executescript(schema_sql)
    print(f"[db] Schema initialized at {config.DB_PATH}")


def upsert(conn, table, row: dict, conflict_keys: list):
    """
    Generic upsert helper: INSERT ... ON CONFLICT(...) DO UPDATE SET ...
    row: dict of column -> value
    conflict_keys: columns forming the unique/primary key constraint
    """
    columns = list(row.keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    update_clause = ", ".join(
        f"{c}=excluded.{c}" for c in columns if c not in conflict_keys
    )
    conflict_clause = ", ".join(conflict_keys)

    sql = f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT({conflict_clause}) DO UPDATE SET {update_clause}
    """
    conn.execute(sql, list(row.values()))


if __name__ == "__main__":
    init_db()
