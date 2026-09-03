"""
Statistical testing query interface — the "Final Goal" queries from the
spec, e.g.:
  - Show ROI of SP mismatch edge when xERA gap > 0.75
  - Bullpen fatigue games with 2+ run underdogs
  - Market overreaction after 6+ run blowouts

These read from `edge_results` (joined with `edges`/`odds`/`outcomes` as
needed) which is populated by pipeline.evaluate over time. The more days
of history you accumulate, the more statistically meaningful these get —
a handful of games will not produce reliable ROI estimates.

Usage examples:
    python -m reports.query_lab roi --edge-type sp_mismatch --min-signal 0.075
    python -m reports.query_lab roi --edge-type bullpen_fatigue
    python -m reports.query_lab roi --edge-type overreaction
    python -m reports.query_lab summary
"""
import sys

sys.path.append(".")

from db.database import connection


def roi_report(edge_type: str, min_signal: float = None):
    query = "SELECT * FROM edge_results WHERE edge_type = ?"
    params = [edge_type]
    if min_signal is not None:
        query += " AND ABS(signal_value) >= ?"
        params.append(min_signal)

    with connection() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print(f"No results found for edge_type='{edge_type}'"
              + (f" with |signal| >= {min_signal}" if min_signal else "")
              + ". Accumulate more history via pipeline.evaluate.")
        return

    n = len(rows)
    wins = sum(1 for r in rows if r["result"] == "win")
    losses = sum(1 for r in rows if r["result"] == "loss")
    total_staked = sum(r["stake"] for r in rows)
    total_profit = sum(r["profit_units"] or 0 for r in rows)
    roi_pct = (total_profit / total_staked * 100) if total_staked else 0
    hit_rate = (wins / n * 100) if n else 0
    clv_values = [r["clv_pct"] for r in rows if r["clv_pct"] is not None]
    avg_clv = sum(clv_values) / len(clv_values) if clv_values else None

    print(f"\n=== ROI Report: {edge_type} ===")
    if min_signal is not None:
        print(f"Filter: |signal_value| >= {min_signal}")
    print(f"Sample size:   {n} bets")
    print(f"Record:        {wins}-{losses}")
    print(f"Hit rate:      {hit_rate:.1f}%")
    print(f"Total staked:  {total_staked:.1f}u")
    print(f"Total profit:  {total_profit:+.2f}u")
    print(f"ROI:           {roi_pct:+.2f}%")
    if avg_clv is not None:
        print(f"Avg CLV:       {avg_clv:+.2f}%")
    if n < 30:
        print("\n[!] Sample size below 30 — treat this ROI as noisy, not conclusive.")
    print()


def summary_report():
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT edge_type,
                   COUNT(*) as n,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                   SUM(stake) as staked,
                   SUM(profit_units) as profit,
                   AVG(clv_pct) as avg_clv
            FROM edge_results
            GROUP BY edge_type
            """
        ).fetchall()

    if not rows:
        print("No edge_results yet. Run pipeline.evaluate after games complete.")
        return

    print("\n=== Edge Summary (all-time) ===")
    print(f"{'Edge Type':<20} {'N':>5} {'Hit%':>7} {'ROI%':>8} {'AvgCLV%':>9}")
    print("-" * 52)
    for r in rows:
        hit_pct = (r["wins"] / r["n"] * 100) if r["n"] else 0
        roi_pct = (r["profit"] / r["staked"] * 100) if r["staked"] else 0
        clv = f"{r['avg_clv']:+.2f}" if r["avg_clv"] is not None else "-"
        print(f"{r['edge_type']:<20} {r['n']:>5} {hit_pct:>6.1f}% {roi_pct:>+7.2f}% {clv:>9}")
    print()


def bullpen_fatigue_vs_underdogs(min_dog_price: int = 100):
    """
    'Bullpen fatigue games with 2+ run underdogs' — interpreted here as
    underdogs priced at or worse than +100 moneyline-equivalent AND on the
    fatigued side of a flagged bullpen_fatigue signal. (Run-line specific
    filtering can be added once run-line odds are populated historically.)
    """
    query = """
        SELECT er.* FROM edge_results er
        WHERE er.edge_type = 'bullpen_fatigue'
          AND er.odds_taken >= ?
    """
    with connection() as conn:
        rows = conn.execute(query, (min_dog_price,)).fetchall()

    if not rows:
        print(f"No bullpen_fatigue underdog (>= +{min_dog_price}) results found yet.")
        return

    n = len(rows)
    wins = sum(1 for r in rows if r["result"] == "win")
    profit = sum(r["profit_units"] or 0 for r in rows)
    staked = sum(r["stake"] for r in rows)
    print(f"\n=== Bullpen Fatigue + Underdog (>= +{min_dog_price}) ===")
    print(f"N={n}, Hit rate={wins/n*100:.1f}%, ROI={profit/staked*100:+.2f}%\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Query historical edge performance")
    sub = parser.add_subparsers(dest="command", required=True)

    roi_p = sub.add_parser("roi", help="ROI/hit-rate/CLV for one edge type")
    roi_p.add_argument("--edge-type", required=True, choices=["sp_mismatch", "bullpen_fatigue", "overreaction"])
    roi_p.add_argument("--min-signal", type=float, default=None)

    sub.add_parser("summary", help="All-time summary across all edge types")

    dog_p = sub.add_parser("bullpen-underdogs", help="Bullpen fatigue + underdog filter")
    dog_p.add_argument("--min-price", type=int, default=100)

    args = parser.parse_args()

    if args.command == "roi":
        roi_report(args.edge_type, args.min_signal)
    elif args.command == "summary":
        summary_report()
    elif args.command == "bullpen-underdogs":
        bullpen_fatigue_vs_underdogs(args.min_price)
