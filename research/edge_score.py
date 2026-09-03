"""
Edge Score engine.

Combines every registered edge into one weighted composite score per
game, where weights are derived SOLELY from each edge's out-of-sample
(test-window) historical ROI — never from train-window or all-data
performance, to avoid baking overfitting into the weights themselves.

Weighting method (deliberately simple and inspectable):
  weight(edge) = max(0, test_roi_pct(edge)) / sum(max(0, test_roi_pct(e)) for e in edges)
i.e. edges with negative or zero out-of-sample ROI get zero weight and
don't contribute to the score at all — they're not allowed to cancel out
a good edge or add noise. If every edge has non-positive test ROI, all
weights are zero and every game scores 0 (correctly: no evidence of edge
anywhere yet).

edge_score(game) = sum(weight(edge) * normalized_signal(edge, game) for edges firing on this game)
where normalized_signal scales signal_value into [0, 1] using the edge's
registered value_range, so a bullpen fatigue index of "8" and an SP
mismatch of "0.08" contribute comparably rather than whichever happens to
have larger raw numbers dominating.

This is intentionally NOT a probability or a bet sizing recommendation —
it's a relative ranking so you can ask "which qualified games looked
strongest today," not "bet X% of bankroll on this game."
"""
import sys

sys.path.append(".")

from db.database import connection
from research.edge_registry import list_edges
from research.data_loader import build_research_dataset
from research.threshold_optimizer import _split_train_test, _metrics_for_bucket
import research.core_edges_adapter  # noqa: F401


def compute_edge_weights(train_frac: float = 0.7, min_test_n: int = 50):
    """
    Returns dict: edge_name -> weight (0 to 1, sums to 1 across edges with
    positive out-of-sample ROI). Edges with fewer than min_test_n
    out-of-sample bets get weight 0 regardless of ROI — too little
    evidence to trust yet, not "no edge."

    Defaults here follow docs/qualification_policy.md section 1 (min N=50
    before an edge can carry nonzero weight) and section 3 (CLV floor: an
    edge with positive ROI but non-positive average CLV does not qualify,
    since CLV is a more reliable early indicator than a short-run win-loss
    record). Changing these defaults is an amendment under policy section 7
    — don't loosen them just because a specific edge is close.
    """
    edges = list_edges()
    raw_scores = {}

    for edge_def in edges:
        records = build_research_dataset([edge_def.name])
        if not records:
            raw_scores[edge_def.name] = 0.0
            continue
        _, test = _split_train_test(records, train_frac)
        metrics = _metrics_for_bucket(test)

        clv_vals = [r["clv_pct"] for r in test if r["clv_pct"] is not None]
        avg_clv = sum(clv_vals) / len(clv_vals) if clv_vals else None

        fails_n = metrics["n"] < min_test_n
        fails_roi = metrics["roi_pct"] is None or metrics["roi_pct"] <= 0
        fails_clv = avg_clv is None or avg_clv <= 0

        if fails_n or fails_roi or fails_clv:
            raw_scores[edge_def.name] = 0.0
        else:
            raw_scores[edge_def.name] = metrics["roi_pct"]

    total = sum(raw_scores.values())
    if total <= 0:
        return {name: 0.0 for name in raw_scores}
    return {name: score / total for name, score in raw_scores.items()}


def _normalize(value, value_range):
    lo, hi = value_range
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def score_game(conn, game_id: str, weights: dict = None):
    """
    Returns (edge_score, contributing_edges) for one game.
    edge_score is in [0, 1]. contributing_edges lists which edges fired
    and their normalized contribution, for transparency (never a black box).
    """
    if weights is None:
        weights = compute_edge_weights()

    edges = list_edges()
    score = 0.0
    contributions = []
    sides_favored = {}

    for edge_def in edges:
        w = weights.get(edge_def.name, 0.0)
        if w <= 0:
            continue
        out = edge_def.compute_fn(conn, game_id)
        if not out or out.get("signal_value") is None:
            continue
        norm = _normalize(out["signal_value"], edge_def.value_range)
        contribution = w * norm
        score += contribution
        contributions.append({
            "edge": edge_def.name, "weight": w, "raw_signal": out["signal_value"],
            "normalized": norm, "contribution": contribution, "side": out.get("side"),
        })
        if out.get("side"):
            sides_favored[out["side"]] = sides_favored.get(out["side"], 0) + contribution

    consensus_side = max(sides_favored, key=sides_favored.get) if sides_favored else None
    return score, contributions, consensus_side


def qualify_games(date_str: str, min_score: float = 0.15, min_test_n: int = 50):
    """
    The 'Bet Qualification Engine' step: returns games whose composite
    Edge Score clears min_score, ranked highest first. This is a filtered,
    ranked list — NOT a bet placement action and NOT a stake size. It's
    the evidence-based shortlist you'd review manually before deciding
    anything.
    """
    weights = compute_edge_weights(min_test_n=min_test_n)
    if all(w == 0 for w in weights.values()):
        print("No edge currently has enough positive out-of-sample history "
              "to be weighted. Accumulate more settled games before "
              "qualifying anything — an all-zero weight set is the correct, "
              "honest output here, not a bug.")
        return []

    qualified = []
    with connection() as conn:
        game_ids = [r["game_id"] for r in conn.execute(
            "SELECT game_id FROM games WHERE date=?", (date_str,)
        ).fetchall()]
        for gid in game_ids:
            score, contributions, side = score_game(conn, gid, weights)
            if score >= min_score:
                game_row = conn.execute("SELECT * FROM games WHERE game_id=?", (gid,)).fetchone()
                qualified.append({
                    "game_id": gid,
                    "matchup": f"{game_row['away_team']}@{game_row['home_team']}",
                    "edge_score": score,
                    "consensus_side": side,
                    "contributions": contributions,
                })

    qualified.sort(key=lambda x: x["edge_score"], reverse=True)
    return qualified


def print_qualification_report(date_str: str, min_score: float = 0.15):
    weights = compute_edge_weights()
    print(f"\n=== Edge Weights (out-of-sample ROI based) ===")
    for name, w in weights.items():
        print(f"  {name:<20} weight={w:.3f}")

    qualified = qualify_games(date_str, min_score)
    print(f"\n=== Qualified Games — {date_str} (Edge Score >= {min_score}) ===")
    if not qualified:
        print("None qualified.\n")
        return
    for q in qualified:
        print(f"\n{q['matchup']}  |  Edge Score: {q['edge_score']:.3f}  |  Leans: {q['consensus_side']}")
        for c in q["contributions"]:
            print(f"    {c['edge']:<18} signal={c['raw_signal']:.3f}  side={c['side']:<5}  contribution={c['contribution']:.3f}")
    print()


if __name__ == "__main__":
    import argparse
    from datetime import date as _date
    parser = argparse.ArgumentParser(description="Compute weighted Edge Score and qualify games")
    parser.add_argument("--date", default=_date.today().isoformat())
    parser.add_argument("--min-score", type=float, default=0.15)
    args = parser.parse_args()
    print_qualification_report(args.date, args.min_score)
