"""
Step 3: Feature / edge computation.

Computes three signals per game and stores them in the `edges` table:

  Edge 1 — SP mismatch:
    sp_edge_score = market_implied_prob_home - model_implied_prob_home
    (model prob derived from xERA gap via a simple logistic mapping;
     positive score = model likes home more than the market does)

  Edge 2 — Bullpen fatigue:
    bullpen_fatigue_index = weighted combo of innings thrown in last 3
    days + extra-innings flag, per team. Higher = more fatigued.

  Edge 3 — Market overreaction:
    Flags games where a team's last outing was a blowout (margin >= 6)
    and the market has moved the line >= a threshold in the "expected"
    overreaction direction (fading the team that blew out an opponent,
    or piling onto the team that got blown out).

This module does NOT predict winners or generate bet recommendations —
it only quantifies mismatches for later historical/statistical testing,
per project constraints.
"""
import math
import sys

sys.path.append(".")

from db.database import connection, upsert

# --- Tunable constants (kept explicit/visible rather than "magic numbers") ---
XERA_LOGISTIC_SCALE = 0.4      # controls how sharply xERA gap maps to win prob
BULLPEN_FATIGUE_WEIGHT_INNINGS = 1.0
BULLPEN_FATIGUE_WEIGHT_EXTRA_INNINGS = 1.5
OVERREACTION_MARGIN_THRESHOLD = 6      # runs, "blowout" cutoff
OVERREACTION_LINE_MOVE_THRESHOLD = 0.02  # 2% implied-prob shift, see below


def american_to_implied_prob(odds: int) -> float:
    if odds is None:
        return None
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)


def xera_gap_to_model_prob_home(home_xera: float, away_xera: float) -> float:
    """
    Simple logistic mapping from xERA gap to an implied home win probability.
    This is intentionally a naive baseline model — NOT a production betting
    model — used only to quantify the gap between "what the pitching
    matchup alone suggests" and "what the market is pricing in", per the
    project's constraint against building a full predictive model.
    """
    if home_xera is None or away_xera is None:
        return None
    gap = away_xera - home_xera  # positive gap favors home (away pitcher worse)
    return 1 / (1 + math.exp(-gap / XERA_LOGISTIC_SCALE))


def compute_sp_edge(conn, game_id: str):
    starter = conn.execute(
        "SELECT * FROM starters WHERE game_id=?", (game_id,)
    ).fetchone()
    if not starter:
        return None

    model_prob_home = xera_gap_to_model_prob_home(starter["home_xERA"], starter["away_xERA"])
    if model_prob_home is None:
        return None

    # Use closing odds if available, else opening, from any sportsbook row (avg if multiple).
    odds_rows = conn.execute(
        "SELECT * FROM odds WHERE game_id=?", (game_id,)
    ).fetchall()
    if not odds_rows:
        market_prob_home = None
    else:
        probs = []
        for r in odds_rows:
            ml = r["closing_moneyline_home"] or r["opening_moneyline_home"]
            p = american_to_implied_prob(ml)
            if p is not None:
                probs.append(p)
        market_prob_home = sum(probs) / len(probs) if probs else None

    sp_edge_score = None
    if market_prob_home is not None:
        sp_edge_score = model_prob_home - market_prob_home

    return {
        "sp_model_implied_prob_home": model_prob_home,
        "sp_market_implied_prob_home": market_prob_home,
        "sp_edge_score": sp_edge_score,
    }


def compute_bullpen_fatigue(conn, game_id: str, home_team: str, away_team: str, date_str: str):
    def fatigue_for(team):
        row = conn.execute(
            "SELECT * FROM team_form WHERE team=? AND date=?", (team, date_str)
        ).fetchone()
        if not row:
            return None
        innings = row["bullpen_innings_last_3_days"] or 0
        extra_innings_flag = row["extra_innings_last_game"] or 0
        return (
            BULLPEN_FATIGUE_WEIGHT_INNINGS * innings
            + BULLPEN_FATIGUE_WEIGHT_EXTRA_INNINGS * extra_innings_flag
        )

    return {
        "bullpen_fatigue_index_home": fatigue_for(home_team),
        "bullpen_fatigue_index_away": fatigue_for(away_team),
    }


def compute_overreaction(conn, game_id: str, home_team: str, away_team: str, date_str: str):
    """
    Looks at each team's last_game_margin (signed: + = big win, - = big
    loss) and whether the current closing line has moved meaningfully
    relative to the opening line in the direction consistent with the
    market overreacting to that recent result.
    """
    home_form = conn.execute(
        "SELECT * FROM team_form WHERE team=? AND date=?", (home_team, date_str)
    ).fetchone()
    away_form = conn.execute(
        "SELECT * FROM team_form WHERE team=? AND date=?", (away_team, date_str)
    ).fetchone()

    odds_row = conn.execute(
        "SELECT * FROM odds WHERE game_id=? LIMIT 1", (game_id,)
    ).fetchone()

    flag = 0
    direction = None

    if odds_row and odds_row["opening_moneyline_home"] and odds_row["closing_moneyline_home"]:
        open_prob_home = american_to_implied_prob(odds_row["opening_moneyline_home"])
        close_prob_home = american_to_implied_prob(odds_row["closing_moneyline_home"])
        line_move = close_prob_home - open_prob_home

        home_blowout_win = home_form and home_form["last_game_margin"] and home_form["last_game_margin"] >= OVERREACTION_MARGIN_THRESHOLD
        away_blowout_win = away_form and away_form["last_game_margin"] and away_form["last_game_margin"] >= OVERREACTION_MARGIN_THRESHOLD

        # If home team just blew someone out, and market has since pushed
        # MORE money on home (line moved further toward home) -> potential
        # overreaction to chase; flag it for the "fade the public" test.
        if home_blowout_win and line_move >= OVERREACTION_LINE_MOVE_THRESHOLD:
            flag = 1
            direction = "home_faded"  # candidate to fade the recent-blowout winner
        elif away_blowout_win and line_move <= -OVERREACTION_LINE_MOVE_THRESHOLD:
            flag = 1
            direction = "away_faded"

    return {"overreaction_flag": flag, "overreaction_direction": direction}


def compute_edges_for_game(conn, game_id: str):
    game = conn.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
    if not game:
        return

    result = {"game_id": game_id}

    sp = compute_sp_edge(conn, game_id)
    if sp:
        result.update(sp)

    bullpen = compute_bullpen_fatigue(conn, game_id, game["home_team"], game["away_team"], game["date"])
    result.update(bullpen)

    overreaction = compute_overreaction(conn, game_id, game["home_team"], game["away_team"], game["date"])
    result.update(overreaction)

    # Fill any missing keys with None so upsert has a consistent column set
    for key in (
        "sp_edge_score", "sp_model_implied_prob_home", "sp_market_implied_prob_home",
        "bullpen_fatigue_index_home", "bullpen_fatigue_index_away",
        "overreaction_flag", "overreaction_direction",
    ):
        result.setdefault(key, None)

    upsert(conn, "edges", result, conflict_keys=["game_id"])


def run(date_str: str):
    with connection() as conn:
        game_ids = [r["game_id"] for r in conn.execute(
            "SELECT game_id FROM games WHERE date=?", (date_str,)
        ).fetchall()]
        for gid in game_ids:
            compute_edges_for_game(conn, gid)
    print(f"[edges] Computed edges for {len(game_ids)} games on {date_str}")


if __name__ == "__main__":
    import argparse
    from datetime import date as _date
    parser = argparse.ArgumentParser(description="Compute edge signals for a date")
    parser.add_argument("--date", default=_date.today().isoformat())
    args = parser.parse_args()
    run(args.date)
