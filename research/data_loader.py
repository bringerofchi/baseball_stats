"""
Research data loader.

pipeline/evaluate.py only logs an edge_results row once a *fixed* threshold
has already fired (e.g. |sp_edge_score| >= 0.03). That's fine for the
original daily report, but it means edge_results can't answer "what would
ROI have looked like at a 5% threshold vs an 8% threshold?" — the games
that didn't clear 3% were never recorded at all.

This loader re-computes each registered edge's raw signal_value for EVERY
settled game (has an outcome), regardless of whether it would have fired
under any particular threshold, and simulates the flat-stake bet outcome
for whichever side the edge favored. That gives the threshold optimizer
and combination analyzer a complete, threshold-agnostic dataset to slice.

Returns a list of dicts (or a pandas DataFrame if pandas is available):
    game_id, date, edge_type, signal_value, side, odds_taken,
    closing_odds, clv_pct, result, profit_units
"""
import sys

sys.path.append(".")

from db.database import connection
from pipeline.evaluate import _american_profit, _clv_pct
from research.edge_registry import list_edges
import research.core_edges_adapter  # noqa: F401 — ensures core edges are registered


def _settle_side(conn, game_id, side):
    """Given the side an edge favored, look up odds/outcome and compute the
    flat-1u bet result. Returns None if data is missing (e.g. no odds row)."""
    odds_row = conn.execute("SELECT * FROM odds WHERE game_id=? LIMIT 1", (game_id,)).fetchone()
    outcome_row = conn.execute("SELECT * FROM outcomes WHERE game_id=?", (game_id,)).fetchone()
    if not odds_row or not outcome_row or side not in ("home", "away"):
        return None

    odds_taken = odds_row["opening_moneyline_home"] if side == "home" else odds_row["opening_moneyline_away"]
    closing_odds = odds_row["closing_moneyline_home"] if side == "home" else odds_row["closing_moneyline_away"]
    if odds_taken is None:
        return None

    result = "win" if side == outcome_row["winner"] else "loss"
    profit = _american_profit(1.0, odds_taken) if result == "win" else -1.0
    clv = _clv_pct(odds_taken, closing_odds)

    return {
        "odds_taken": odds_taken,
        "closing_odds": closing_odds,
        "clv_pct": clv,
        "result": result,
        "profit_units": profit,
    }


def build_research_dataset(edge_names: list = None):
    """
    edge_names: optional list to restrict to specific registered edges.
    Returns a list of dict records, one per (settled game, edge_type) pair
    where the edge produced a non-null signal.
    """
    edges = list_edges()
    if edge_names:
        edges = [e for e in edges if e.name in edge_names]

    records = []
    with connection() as conn:
        game_rows = conn.execute(
            """SELECT g.game_id, g.date FROM games g
               INNER JOIN outcomes o ON g.game_id = o.game_id"""
        ).fetchall()

        for g in game_rows:
            game_id, date_str = g["game_id"], g["date"]
            for edge_def in edges:
                out = edge_def.compute_fn(conn, game_id)
                if not out or out.get("signal_value") is None or not out.get("side"):
                    continue
                settled = _settle_side(conn, game_id, out["side"])
                if not settled:
                    continue
                records.append({
                    "game_id": game_id,
                    "date": date_str,
                    "edge_type": edge_def.name,
                    "signal_value": out["signal_value"],
                    "side": out["side"],
                    **settled,
                })
    return records


def as_dataframe(edge_names: list = None):
    import pandas as pd
    records = build_research_dataset(edge_names)
    return pd.DataFrame(records)
