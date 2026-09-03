"""
Step 4: Post-game evaluation.

After a game finishes:
  1. Store final score/outcome in `outcomes`.
  2. For each edge signal that fired on this game, log a row in
     `edge_results` recording:
       - the side the edge "pointed to" (not a recommendation to bet,
         just which side the signal favored, for backtesting)
       - odds at signal time vs. closing odds -> CLV %
       - win/loss/push result -> hit rate
       - profit in flat units (1u stake) -> ROI

This module assumes a flat 1-unit staking model for backtesting purposes.
It does NOT place bets or interact with any sportsbook — it is purely
historical record-keeping for statistical testing.
"""
import sys
from datetime import date as _date

sys.path.append(".")

from db.database import connection, upsert
from pipeline.edges import american_to_implied_prob

SP_EDGE_SCORE_THRESHOLD = 0.03      # min |sp_edge_score| to count as a "signal"
BULLPEN_FATIGUE_DIFF_THRESHOLD = 3.0  # min fatigue index diff between teams


def _american_profit(stake: float, odds: int) -> float:
    """Profit (excluding stake) for a winning bet at American odds."""
    if odds > 0:
        return stake * (odds / 100)
    else:
        return stake * (100 / -odds)


def _clv_pct(odds_taken: int, closing_odds: int) -> float:
    """
    CLV as % difference in implied probability: getting a better (higher
    payout / lower implied prob) number than closing = positive CLV.
    """
    if odds_taken is None or closing_odds is None:
        return None
    p_taken = american_to_implied_prob(odds_taken)
    p_close = american_to_implied_prob(closing_odds)
    if p_taken is None or p_close is None or p_close == 0:
        return None
    return (p_close - p_taken) / p_close * 100


def store_outcome(conn, game_id: str, final_home: int, final_away: int, innings_played: int = 9):
    winner = "home" if final_home > final_away else "away"
    row = {
        "game_id": game_id,
        "final_score_home": final_home,
        "final_score_away": final_away,
        "winner": winner,
        "total_runs": final_home + final_away,
        "innings_played": innings_played,
    }
    upsert(conn, "outcomes", row, conflict_keys=["game_id"])
    return winner


def auto_store_outcomes(conn, date_str: str):
    """
    Pulls the day's games from MLB Stats API and stores outcomes for any
    that have finished, instead of requiring manual score entry per game.
    Games not yet final are simply skipped (not an error) — re-running
    this later in the day picks up newly-finished games.

    Returns (stored_count, still_in_progress_count, missing_score_count).
    missing_score_count covers the edge case where a game is marked Final
    but the score fields weren't extractable — surfaced explicitly rather
    than silently skipped, since that combination shouldn't normally happen.
    """
    from clients.mlb_stats_api import MLBStatsAPIClient
    client = MLBStatsAPIClient()
    games = client.get_schedule(date_str)

    stored = 0
    in_progress = 0
    missing_score = []

    for g in games:
        game_id = str(g["gamePk"])
        if not client.is_game_final(g):
            in_progress += 1
            continue

        home_score, away_score = client.extract_final_score(g)
        if home_score is None or away_score is None:
            missing_score.append(game_id)
            continue

        store_outcome(conn, game_id, home_score, away_score)
        stored += 1

    print(f"[settle] Auto-stored outcomes for {stored} finished game(s) on {date_str}.")
    if in_progress:
        print(f"[settle] {in_progress} game(s) not final yet — skipped, re-run settle later "
              f"today to pick them up.")
    if missing_score:
        print(f"[settle] WARNING: {len(missing_score)} game(s) marked Final but no score could "
              f"be extracted — these need manual entry via the dashboard's Store Outcome form. "
              f"game_ids: {missing_score}")

    return stored, in_progress, len(missing_score)


def _log_edge_result(conn, game_id, edge_type, side_taken, odds_row, winner, signal_value):
    if not odds_row:
        return
    sportsbook = odds_row["sportsbook"]
    odds_taken = odds_row["opening_moneyline_home"] if side_taken == "home" else odds_row["opening_moneyline_away"]
    closing_odds = odds_row["closing_moneyline_home"] if side_taken == "home" else odds_row["closing_moneyline_away"]

    if odds_taken is None:
        return

    result = "win" if side_taken == winner else "loss"
    stake = 1.0
    profit = _american_profit(stake, odds_taken) if result == "win" else -stake

    row = {
        "game_id": game_id,
        "edge_type": edge_type,
        "side_taken": side_taken,
        "sportsbook": sportsbook,
        "stake": stake,
        "odds_taken": odds_taken,
        "closing_odds": closing_odds,
        "clv_pct": _clv_pct(odds_taken, closing_odds),
        "result": result,
        "profit_units": profit,
        "signal_value": signal_value,
    }
    # Upsert, not raw insert: re-running Settle for an already-evaluated
    # date must update the existing row, not duplicate it. See schema.sql's
    # UNIQUE(game_id, edge_type, sportsbook) comment for why this matters.
    upsert(conn, "edge_results", row, conflict_keys=["game_id", "edge_type", "sportsbook"])


def evaluate_game(conn, game_id: str):
    edge = conn.execute("SELECT * FROM edges WHERE game_id=?", (game_id,)).fetchone()
    outcome = conn.execute("SELECT * FROM outcomes WHERE game_id=?", (game_id,)).fetchone()
    odds_row = conn.execute("SELECT * FROM odds WHERE game_id=? LIMIT 1", (game_id,)).fetchone()

    if not edge or not outcome:
        return

    winner = outcome["winner"]

    # Edge 1: SP mismatch -> side favored is whichever side model_prob exceeds market_prob
    if edge["sp_edge_score"] is not None and abs(edge["sp_edge_score"]) >= SP_EDGE_SCORE_THRESHOLD:
        side = "home" if edge["sp_edge_score"] > 0 else "away"
        _log_edge_result(conn, game_id, "sp_mismatch", side, odds_row, winner, edge["sp_edge_score"])

    # Edge 2: Bullpen fatigue -> favor the LESS fatigued team (opponent of the fatigued one)
    h_fatigue = edge["bullpen_fatigue_index_home"]
    a_fatigue = edge["bullpen_fatigue_index_away"]
    if h_fatigue is not None and a_fatigue is not None:
        diff = a_fatigue - h_fatigue  # positive = away more fatigued -> favor home
        if abs(diff) >= BULLPEN_FATIGUE_DIFF_THRESHOLD:
            side = "home" if diff > 0 else "away"
            _log_edge_result(conn, game_id, "bullpen_fatigue", side, odds_row, winner, diff)

    # Edge 3: Market overreaction -> fade the team the flag identifies
    if edge["overreaction_flag"]:
        if edge["overreaction_direction"] == "home_faded":
            side = "away"  # fading home means betting away
        elif edge["overreaction_direction"] == "away_faded":
            side = "home"
        else:
            side = None
        if side:
            _log_edge_result(conn, game_id, "overreaction", side, odds_row, winner, 1.0)


def run(date_str: str, auto_fetch_outcomes: bool = True):
    with connection() as conn:
        if auto_fetch_outcomes:
            auto_store_outcomes(conn, date_str)

        game_ids = [r["game_id"] for r in conn.execute(
            "SELECT game_id FROM games WHERE date=?", (date_str,)
        ).fetchall()]
        for gid in game_ids:
            evaluate_game(conn, gid)
    print(f"[evaluate] Evaluated {len(game_ids)} games on {date_str}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate ROI/CLV/hit-rate for a date's games")
    parser.add_argument("--date", default=_date.today().isoformat())
    parser.add_argument("--no-auto-fetch", action="store_true",
                         help="Skip auto-fetching outcomes from MLB Stats API; "
                              "use only outcomes already stored (e.g. entered manually).")
    args = parser.parse_args()
    run(args.date, auto_fetch_outcomes=not args.no_auto_fetch)
