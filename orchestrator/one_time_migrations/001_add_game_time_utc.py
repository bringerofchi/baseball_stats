"""
Run this ONCE, before the next ingest run (manual or automated), after
applying the database.py and ingest.py patches.

Why this is separate from task_state.ensure_schema(): game_time_utc is
written by ingest_games() regardless of whether the orchestrator is
involved at all (e.g. a manual dashboard-triggered ingest hits this
too), so Flask can't be left depending on the orchestrator having run
first to create the column. This script has no import dependency on
the orchestrator package — just sqlite3 and config.

Usage (from project root):
    python orchestrator/one_time_migrations/001_add_game_time_utc.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import config


def main():
    conn = sqlite3.connect(config.DB_PATH)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(games)").fetchall()}
    if "game_time_utc" in existing:
        print(f"[migration] games.game_time_utc already exists in {config.DB_PATH} — nothing to do.")
    else:
        conn.execute("ALTER TABLE games ADD COLUMN game_time_utc TEXT")
        conn.commit()
        print(f"[migration] Added games.game_time_utc to {config.DB_PATH}.")
        print("[migration] NOTE: existing rows will have NULL game_time_utc until the "
              "next ingest_games() run repopulates them (source: gameDate in the "
              "MLB Stats API schedule response).")
    conn.close()


if __name__ == "__main__":
    main()
