"""
Step 5: Output system — "MLB Edge Board" daily report.

Prints a per-game table of computed signals. This is a descriptive report
of what the data shows, not a betting recommendation engine — the
`recommended lean` column simply names which side each edge points toward,
for the person doing their own analysis to review.

Usage:
    python -m reports.edge_board --date 2026-07-06
"""
import sys
from datetime import date as _date

sys.path.append(".")

from db.database import connection


def _lean_from_edges(edge_row):
    leans = []
    if edge_row["sp_edge_score"] is not None and abs(edge_row["sp_edge_score"]) >= 0.03:
        side = "home" if edge_row["sp_edge_score"] > 0 else "away"
        leans.append(f"SP->{side}")
    h = edge_row["bullpen_fatigue_index_home"]
    a = edge_row["bullpen_fatigue_index_away"]
    if h is not None and a is not None and abs(a - h) >= 3.0:
        side = "home" if a > h else "away"
        leans.append(f"Bullpen->{side}")
    if edge_row["overreaction_flag"]:
        fade_target = edge_row["overreaction_direction"]
        leans.append(f"Overreaction({fade_target})")
    return ", ".join(leans) if leans else "-"


def generate(date_str: str):
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT g.game_id, g.home_team, g.away_team, g.stadium,
                   e.sp_edge_score, e.sp_model_implied_prob_home, e.sp_market_implied_prob_home,
                   e.bullpen_fatigue_index_home, e.bullpen_fatigue_index_away,
                   e.overreaction_flag, e.overreaction_direction
            FROM games g
            LEFT JOIN edges e ON g.game_id = e.game_id
            WHERE g.date = ?
            ORDER BY g.game_id
            """,
            (date_str,),
        ).fetchall()

    if not rows:
        print(f"No games found for {date_str}. Run pipeline.ingest first.")
        return

    header = (
        f"{'Game ID':<12} {'Matchup':<24} {'SP Edge':>9} {'Model%':>8} {'Mkt%':>8} "
        f"{'BullpenH':>9} {'BullpenA':>9} {'Overreact':>10} {'Lean':<28}"
    )
    print(f"\n=== MLB Edge Board — {date_str} ===\n")
    print(header)
    print("-" * len(header))

    for r in rows:
        matchup = f"{r['away_team']}@{r['home_team']}"
        sp_edge = f"{r['sp_edge_score']:.3f}" if r["sp_edge_score"] is not None else "-"
        model_p = f"{r['sp_model_implied_prob_home']*100:.1f}" if r["sp_model_implied_prob_home"] is not None else "-"
        mkt_p = f"{r['sp_market_implied_prob_home']*100:.1f}" if r["sp_market_implied_prob_home"] is not None else "-"
        bh = f"{r['bullpen_fatigue_index_home']:.1f}" if r["bullpen_fatigue_index_home"] is not None else "-"
        ba = f"{r['bullpen_fatigue_index_away']:.1f}" if r["bullpen_fatigue_index_away"] is not None else "-"
        overreact = r["overreaction_direction"] or ("-" if not r["overreaction_flag"] else "flagged")
        lean = _lean_from_edges(r)

        print(
            f"{r['game_id']:<12} {matchup:<24} {sp_edge:>9} {model_p:>8} {mkt_p:>8} "
            f"{bh:>9} {ba:>9} {overreact:>10} {lean:<28}"
        )
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate the daily MLB Edge Board")
    parser.add_argument("--date", default=_date.today().isoformat())
    args = parser.parse_args()
    generate(args.date)
