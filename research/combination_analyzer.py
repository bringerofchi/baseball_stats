"""
Combination analyzer.

Tests pairs (and optionally triples) of registered edges to see if games
where BOTH signals agree on the same side outperform either signal alone.
This is where the spec's examples live: "SP mismatch + bullpen fatigue",
"bullpen fatigue + reverse line movement", etc.

Two edges "agree" on a game if both fired (signal_value >= their
respective threshold) AND favored the same side. Performance is reported
for: edge A alone, edge B alone, and A+B agreeing — so you can see
whether the combination actually adds anything over the better of the two
individually, rather than just assuming stacking signals helps.
"""
import sys
from itertools import combinations

sys.path.append(".")

from research.data_loader import build_research_dataset
from research.threshold_optimizer import _metrics_for_bucket, _split_train_test


def _index_by_game(records: list):
    """dict: game_id -> {edge_type: record}"""
    idx = {}
    for r in records:
        idx.setdefault(r["game_id"], {})[r["edge_type"]] = r
    return idx


def analyze_pair(edge_a: str, edge_b: str, threshold_a: float, threshold_b: float, train_frac: float = 0.7):
    records = build_research_dataset([edge_a, edge_b])
    if not records:
        print(f"No data available for {edge_a} / {edge_b} yet.")
        return None

    by_game = _index_by_game(records)

    alone_a, alone_b, combo = [], [], []
    for game_id, edges_here in by_game.items():
        ra = edges_here.get(edge_a)
        rb = edges_here.get(edge_b)
        a_fires = ra and ra["signal_value"] >= threshold_a
        b_fires = rb and rb["signal_value"] >= threshold_b

        if a_fires:
            alone_a.append(ra)
        if b_fires:
            alone_b.append(rb)
        if a_fires and b_fires and ra["side"] == rb["side"]:
            # Combo bet result = same underlying bet (same side), record once
            combo.append(ra)

    train_combo, test_combo = _split_train_test(combo, train_frac)
    train_a, test_a = _split_train_test(alone_a, train_frac)
    train_b, test_b = _split_train_test(alone_b, train_frac)

    return {
        "edge_a": {"name": edge_a, "train": _metrics_for_bucket(train_a), "test": _metrics_for_bucket(test_a)},
        "edge_b": {"name": edge_b, "train": _metrics_for_bucket(train_b), "test": _metrics_for_bucket(test_b)},
        "combo": {"train": _metrics_for_bucket(train_combo), "test": _metrics_for_bucket(test_combo)},
    }


def print_pair_report(edge_a: str, edge_b: str, threshold_a: float, threshold_b: float, train_frac: float = 0.7):
    result = analyze_pair(edge_a, edge_b, threshold_a, threshold_b, train_frac)
    if not result:
        return

    print(f"\n=== Combination: {edge_a} (>={threshold_a}) + {edge_b} (>={threshold_b}) ===")
    row_fmt = "{:<28} {:>7} {:>10} {:>10}   {:>7} {:>10} {:>10}"
    print(row_fmt.format("", "TrainN", "TrainROI", "TrainHit%", "TestN", "TestROI", "TestHit%"))
    for label, key in ((edge_a + " alone", "edge_a"), (edge_b + " alone", "edge_b"), ("BOTH agree", "combo")):
        d = result[key] if key != "combo" else result["combo"]
        tr, te = d["train"], d["test"]
        tr_roi = f"{tr['roi_pct']:+.1f}%" if tr["roi_pct"] is not None else "-"
        te_roi = f"{te['roi_pct']:+.1f}%" if te["roi_pct"] is not None else "-"
        tr_hit = f"{tr['hit_rate']:.1f}%" if tr["hit_rate"] is not None else "-"
        te_hit = f"{te['hit_rate']:.1f}%" if te["hit_rate"] is not None else "-"
        print(row_fmt.format(label, tr["n"], tr_roi, tr_hit, te["n"], te_roi, te_hit))

    combo_test_n = result["combo"]["test"]["n"]
    print(f"\nCombo test sample size: {combo_test_n}."
          + (" Too small to draw any conclusion yet — combos shrink sample "
             "size fast since both signals must fire and agree." if combo_test_n < 30 else ""))
    print()


def scan_all_pairs(edge_names: list, thresholds: dict, train_frac: float = 0.7):
    """
    thresholds: dict of edge_name -> threshold to use for that edge.
    Runs every unique pair and prints a one-line summary sorted by test ROI.
    """
    summaries = []
    for a, b in combinations(edge_names, 2):
        result = analyze_pair(a, b, thresholds.get(a, 0), thresholds.get(b, 0), train_frac)
        if result:
            summaries.append((a, b, result["combo"]["test"]))

    print("\n=== Pairwise Combination Scan (sorted by test ROI) ===")
    summaries.sort(key=lambda x: (x[2]["roi_pct"] if x[2]["roi_pct"] is not None else -999), reverse=True)
    print(f"{'Edge A':<20} {'Edge B':<20} {'N':>5} {'ROI':>8} {'Hit%':>7}")
    for a, b, m in summaries:
        roi = f"{m['roi_pct']:+.1f}%" if m["roi_pct"] is not None else "-"
        hit = f"{m['hit_rate']:.1f}%" if m["hit_rate"] is not None else "-"
        print(f"{a:<20} {b:<20} {m['n']:>5} {roi:>8} {hit:>7}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analyze edge signal combinations")
    parser.add_argument("--edge-a", required=True)
    parser.add_argument("--edge-b", required=True)
    parser.add_argument("--threshold-a", type=float, required=True)
    parser.add_argument("--threshold-b", type=float, required=True)
    args = parser.parse_args()
    print_pair_report(args.edge_a, args.edge_b, args.threshold_a, args.threshold_b)
