"""
MLB Edge Lab — main orchestrator.

Runs the full daily pipeline in order:
  1. Ingest games/starters/weather/odds (opening snapshot)
  2. Compute edge signals
  3. (Later, closer to game time) re-run ingest with --snapshot closing
  4. (After games finish) evaluate outcomes + log edge_results
  5. Print the Edge Board report

Typical daily cron setup (see README.md for full crontab example):
  - Morning:      python main.py morning   --date today
  - Pre-gametime: python main.py closing   --date today
  - Night/next AM: python main.py settle   --date yesterday
"""
import argparse
import sys
from datetime import date, timedelta

sys.path.append(".")

from db.database import init_db
from pipeline import ingest, edges, evaluate
from reports import edge_board
from logging_setup import logged_run


def resolve_date(token: str) -> str:
    if token == "today":
        return date.today().isoformat()
    if token == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return token  # assume already YYYY-MM-DD


def cmd_morning(date_str):
    ingest.run(date_str, snapshot="opening")
    edges.run(date_str)
    edge_board.generate(date_str)


def cmd_closing(date_str):
    ingest.run(date_str, snapshot="closing")
    edges.run(date_str)  # recompute with closing lines factored in
    edge_board.generate(date_str)


def cmd_settle(date_str):
    """
    Post-game settlement. Auto-fetches final scores from MLB Stats API for
    any finished games (see pipeline.evaluate.auto_store_outcomes) before
    running ROI/CLV/hit-rate evaluation. Games not yet final are skipped,
    not errored — re-run settle later in the day to pick them up. The
    dashboard's manual "Store Outcome" form still exists as a fallback for
    the rare case a game is Final but its score wasn't extractable.
    """
    evaluate.run(date_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB Edge Lab pipeline runner")
    parser.add_argument("command", choices=["init", "morning", "closing", "settle", "report"])
    parser.add_argument("--date", default="today", help="'today', 'yesterday', or YYYY-MM-DD")
    args = parser.parse_args()

    d = resolve_date(args.date)

    if args.command == "init":
        init_db()
    elif args.command == "morning":
        logged_run(f"main.py morning --date {d}", cmd_morning, d)
    elif args.command == "closing":
        logged_run(f"main.py closing --date {d}", cmd_closing, d)
    elif args.command == "settle":
        logged_run(f"main.py settle --date {d}", cmd_settle, d)
    elif args.command == "report":
        logged_run(f"main.py report --date {d}", edge_board.generate, d)
