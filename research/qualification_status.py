"""
Provisional vs. Confirmed status classification.

Implements docs/qualification_policy.md sections 5 (status definitions) and
6 (decay monitoring / automatic downgrade). This is deliberately a separate
module from threshold_optimizer.py and edge_score.py — it consumes their
qualification verdicts rather than re-implementing the statistics, so the
"what counts as evidence" logic stays in one place (threshold_optimizer)
and the "how much evidence, and is it still holding up" logic stays here.

Status definitions (see policy for full rationale):
  - NOT_QUALIFIED: fails the section 1-4 gates (sample size, corrected CI,
    CLV) at whatever threshold is being evaluated.
  - PROVISIONAL: clears sections 1-4 at the minimum bar (default N=50 for
    a single edge). Worth watching, not a recommendation.
  - CONFIRMED: clears sections 1-4 AND has >= 500 out-of-sample bets AND
    its most recent 100 bets (a window not used to originally select the
    threshold) independently show positive ROI and positive CLV. This is
    the re-validation-on-a-later-window requirement from section 5,
    approximated here via the trailing-100 slice of the test window rather
    than a third data split, since a third split would shrink an already
    scarce out-of-sample set.
  - A CONFIRMED edge whose trailing 100 bets turn negative on ROI or CLV
    is downgraded back to PROVISIONAL (section 6) — this function always
    re-derives status from current data rather than reading a stored
    label, so there is no stale "Confirmed" badge sitting around.
"""
import sys

sys.path.append(".")

from research.data_loader import build_research_dataset
from research.threshold_optimizer import (
    _split_train_test, _metrics_for_bucket, bonferroni_confidence,
)

CONFIRMED_MIN_N = 500
TRAILING_WINDOW_N = 100


def _trailing_slice(records: list, n: int):
    """Most recent n bets by date, for the trailing re-validation check."""
    ordered = sorted(records, key=lambda r: r["date"])
    return ordered[-n:] if len(ordered) >= n else ordered


def classify_status(edge_name: str, threshold: float, train_frac: float = 0.7,
                     min_n_provisional: int = 50, num_comparisons: int = 1):
    """
    threshold: the specific signal_value cutoff being evaluated (i.e. you've
    already picked a threshold via threshold_optimizer — this checks whether
    THAT choice earns Provisional or Confirmed status).
    num_comparisons: how many thresholds/combinations were scanned to arrive
    at this one, for the Bonferroni correction (policy section 4). Pass the
    same grid size used in threshold_optimizer.optimize_threshold() for
    consistency.
    """
    all_records = build_research_dataset([edge_name])
    if not all_records:
        return {"status": "NOT_QUALIFIED", "reason": "No settled games with this signal yet.", "metrics": None}

    _, test = _split_train_test(all_records, train_frac)
    bucket = [r for r in test if r["signal_value"] >= threshold]

    corrected_conf = bonferroni_confidence(0.95, num_comparisons)
    metrics = _metrics_for_bucket(bucket, corrected_conf)

    if metrics["n"] < min_n_provisional or not metrics["qualifies"]:
        return {
            "status": "NOT_QUALIFIED",
            "reason": f"N={metrics['n']} (need >={min_n_provisional}) or fails corrected-CI/CLV gate.",
            "metrics": metrics,
        }

    if metrics["n"] < CONFIRMED_MIN_N:
        return {
            "status": "PROVISIONAL",
            "reason": f"Qualifies but N={metrics['n']} < {CONFIRMED_MIN_N} required for Confirmed status.",
            "metrics": metrics,
        }

    # Enough total volume to be eligible for Confirmed — now check the
    # trailing window independently re-validates (section 5/6).
    trailing = _trailing_slice(bucket, TRAILING_WINDOW_N)
    trailing_metrics = _metrics_for_bucket(trailing, corrected_conf)
    trailing_roi_ok = trailing_metrics["roi_pct"] is not None and trailing_metrics["roi_pct"] > 0
    trailing_clv_ok = trailing_metrics["avg_clv"] is not None and trailing_metrics["avg_clv"] > 0

    if trailing_roi_ok and trailing_clv_ok:
        return {
            "status": "CONFIRMED",
            "reason": f"N={metrics['n']}, trailing {TRAILING_WINDOW_N} bets still ROI+/CLV+.",
            "metrics": metrics,
            "trailing_metrics": trailing_metrics,
        }
    else:
        return {
            "status": "PROVISIONAL",
            "reason": (
                f"N={metrics['n']} clears Confirmed volume, but trailing "
                f"{TRAILING_WINDOW_N} bets failed re-validation "
                f"(ROI={trailing_metrics['roi_pct']}, CLV={trailing_metrics['avg_clv']}) "
                f"— downgraded per policy section 6."
            ),
            "metrics": metrics,
            "trailing_metrics": trailing_metrics,
        }


def print_status_report(edge_name: str, threshold: float, num_comparisons: int = 1):
    result = classify_status(edge_name, threshold, num_comparisons=num_comparisons)
    print(f"\n=== Status: {edge_name} @ threshold {threshold} ===")
    print(f"Status: {result['status']}")
    print(f"Reason: {result['reason']}")
    if result.get("metrics"):
        m = result["metrics"]
        print(f"Out-of-sample N={m['n']}, ROI={m['roi_pct']:+.1f}%, hit rate={m['hit_rate']:.1f}%, "
              f"avg CLV={m['avg_clv']:+.2f}%" if m['avg_clv'] is not None else "")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Classify an edge's Provisional/Confirmed status")
    parser.add_argument("--edge", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--num-comparisons", type=int, default=1,
                         help="How many thresholds were scanned to select this one (Bonferroni correction)")
    args = parser.parse_args()
    print_status_report(args.edge, args.threshold, args.num_comparisons)
