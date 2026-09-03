"""
Threshold optimizer.

Searches a grid of thresholds for a given edge (e.g. SP mismatch at 2%,
3%, 4%, ... 15%) and reports ROI, hit rate, CLV, sample size, and a
confidence interval for each — using WALK-FORWARD validation so the
threshold that "wins" is never chosen using data from the future.

How the walk-forward split works:
  1. Sort all settled games chronologically.
  2. Split into a TRAIN window (older games) and a TEST window (newer
     games) — default 70/30 by date, not by row count (row count would
     let a busy month dominate the split).
  3. For each candidate threshold, compute metrics on TRAIN only, and
     separately on TEST only, and report both. A threshold is trustworthy
     to the extent its TEST performance resembles its TRAIN performance —
     divergence between the two is a straightforward overfitting signal.
  4. Decay check: metrics are also broken into thirds of the test window's
     date range, so you can see if ROI/hit-rate is fading over time
     within the test set itself.

This module does NOT pick "the best" threshold and declare it correct —
it prints the full grid with train vs. test performance and out-of-sample
sample sizes so you can judge how much to trust each one. A threshold
with a great TRAIN number and a mediocre TEST number is a warning sign,
not a tiebreaker in the threshold's favor.
"""
import math
import sys
from statistics import NormalDist

sys.path.append(".")

from research.data_loader import build_research_dataset
from pipeline.edges import american_to_implied_prob


def wilson_interval(wins: int, n: int, confidence: float = 0.95):
    """Wilson score interval for a binomial proportion — more reliable than
    a naive normal approximation at small sample sizes, which is the norm
    here early on."""
    if n == 0:
        return (None, None)
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half_width = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return (max(0.0, center - half_width), min(1.0, center + half_width))


def bonferroni_confidence(base_confidence: float, num_comparisons: int) -> float:
    """
    Per docs/qualification_policy.md section 4: when testing N thresholds
    (or combinations) and only surfacing the best-looking ones, the naive
    95% CI is too permissive — some threshold will clear it by chance alone
    even with zero real edge, purely from how many were tried. This
    corrects the confidence level upward so the CI stays honest under
    multiple comparisons: alpha_corrected = alpha / N.
    """
    if num_comparisons < 1:
        num_comparisons = 1
    alpha = 1 - base_confidence
    corrected_alpha = alpha / num_comparisons
    return 1 - corrected_alpha


def _breakeven_hit_rate(records: list):
    """Average breakeven win probability implied by the odds actually taken
    on these bets — the hit rate needed just to break even, not profit."""
    probs = [american_to_implied_prob(r["odds_taken"]) for r in records if r.get("odds_taken") is not None]
    probs = [p for p in probs if p is not None]
    return sum(probs) / len(probs) * 100 if probs else None


def _split_train_test(records: list, train_frac: float = 0.7):
    dates = sorted(set(r["date"] for r in records))
    if len(dates) < 2:
        return records, []
    cutoff_idx = int(len(dates) * train_frac)
    cutoff_date = dates[cutoff_idx]
    train = [r for r in records if r["date"] < cutoff_date]
    test = [r for r in records if r["date"] >= cutoff_date]
    return train, test


def _metrics_for_bucket(records: list, corrected_confidence: float = 0.95):
    n = len(records)
    if n == 0:
        return {
            "n": 0, "hit_rate": None, "roi_pct": None, "avg_clv": None,
            "ci_low": None, "ci_high": None, "ci_low_corrected": None,
            "breakeven": None, "qualifies": False,
        }
    wins = sum(1 for r in records if r["result"] == "win")
    staked = n * 1.0
    profit = sum(r["profit_units"] for r in records)
    clv_vals = [r["clv_pct"] for r in records if r["clv_pct"] is not None]
    ci_low, ci_high = wilson_interval(wins, n)
    ci_low_corrected, _ = wilson_interval(wins, n, confidence=corrected_confidence)
    breakeven = _breakeven_hit_rate(records)
    avg_clv = sum(clv_vals) / len(clv_vals) if clv_vals else None

    # Qualifies per policy sections 2-3: corrected CI lower bound must clear
    # breakeven AND average CLV must be positive. (Sample-size floor from
    # section 1 is applied by the caller, not here, since it varies by
    # context — single edge vs. combination.)
    qualifies = (
        breakeven is not None
        and ci_low_corrected is not None
        and ci_low_corrected * 100 > breakeven
        and avg_clv is not None
        and avg_clv > 0
    )

    return {
        "n": n,
        "hit_rate": wins / n * 100,
        "roi_pct": profit / staked * 100,
        "avg_clv": avg_clv,
        "ci_low": ci_low * 100 if ci_low is not None else None,
        "ci_high": ci_high * 100 if ci_high is not None else None,
        "ci_low_corrected": ci_low_corrected * 100 if ci_low_corrected is not None else None,
        "breakeven": breakeven,
        "qualifies": qualifies,
    }


def _decay_check(test_records: list, n_buckets: int = 3):
    if not test_records:
        return []
    dates = sorted(set(r["date"] for r in test_records))
    if len(dates) < n_buckets:
        return [_metrics_for_bucket(test_records)]
    chunk_size = max(1, len(dates) // n_buckets)
    buckets = []
    for i in range(n_buckets):
        start = dates[i * chunk_size]
        end = dates[min((i + 1) * chunk_size, len(dates) - 1)]
        chunk = [r for r in test_records if start <= r["date"] <= end]
        m = _metrics_for_bucket(chunk)
        m["period"] = f"{start}..{end}"
        buckets.append(m)
    return buckets


def optimize_threshold(edge_name: str, grid: list = None, train_frac: float = 0.7, min_n: int = 50):
    """
    grid: list of threshold values to test (signal_value >= threshold).
          If None, builds a grid from the edge's registered value_range.
    min_n: sample-size floor from docs/qualification_policy.md section 1
           (default 50, matching the single-edge minimum). A threshold
           result below this is never marked qualifying regardless of its
           CI/CLV, since the CI itself is unreliable at very low N.
    """
    from research.edge_registry import get_edge
    edge_def = get_edge(edge_name)
    if edge_def is None:
        raise ValueError(f"Edge '{edge_name}' is not registered.")

    if grid is None:
        lo, hi = edge_def.value_range
        steps = 10
        grid = [lo + (hi - lo) * i / steps for i in range(1, steps + 1)]

    all_records = build_research_dataset([edge_name])
    if not all_records:
        print(f"No settled games with a '{edge_name}' signal yet. "
              f"Run pipeline.evaluate.store_outcome() for more games first.")
        return []

    train, test = _split_train_test(all_records, train_frac)

    # Bonferroni correction per policy section 4: every threshold in the
    # grid counts as one comparison, since we're scanning all of them and
    # would otherwise be tempted to report only the best-looking one.
    corrected_confidence = bonferroni_confidence(0.95, len(grid))

    results = []
    for threshold in grid:
        train_bucket = [r for r in train if r["signal_value"] >= threshold]
        test_bucket = [r for r in test if r["signal_value"] >= threshold]
        train_m = _metrics_for_bucket(train_bucket, corrected_confidence)
        test_m = _metrics_for_bucket(test_bucket, corrected_confidence)
        test_m["qualifies"] = test_m["qualifies"] and test_m["n"] >= min_n
        results.append({
            "threshold": threshold,
            "train": train_m,
            "test": test_m,
            "decay": _decay_check(test_bucket),
        })
    return results


def print_threshold_report(edge_name: str, grid: list = None, train_frac: float = 0.7, min_n: int = 50):
    results = optimize_threshold(edge_name, grid, train_frac, min_n)
    if not results:
        return

    n_thresholds = len(results)
    corrected_conf = bonferroni_confidence(0.95, n_thresholds)
    print(f"\n=== Threshold Optimization: {edge_name} (walk-forward, train={train_frac:.0%}) ===")
    print(f"Bonferroni-corrected confidence level for this {n_thresholds}-threshold scan: {corrected_conf*100:.2f}% "
          f"(policy section 4 — naive 95% is too permissive when this many thresholds are tested)")
    header = f"{'Threshold':>10} | {'Train N':>7} {'Train ROI':>10} {'Train Hit%':>11} | {'Test N':>7} {'Test ROI':>9} {'Test Hit%':>10} {'CorrCI Low':>11} {'Breakeven':>10} {'QUALIFIES':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        tr, te = r["train"], r["test"]
        tr_roi = f"{tr['roi_pct']:+.1f}%" if tr["roi_pct"] is not None else "-"
        te_roi = f"{te['roi_pct']:+.1f}%" if te["roi_pct"] is not None else "-"
        tr_hit = f"{tr['hit_rate']:.1f}%" if tr["hit_rate"] is not None else "-"
        te_hit = f"{te['hit_rate']:.1f}%" if te["hit_rate"] is not None else "-"
        ci_corr = f"{te['ci_low_corrected']:.1f}%" if te["ci_low_corrected"] is not None else "-"
        breakeven = f"{te['breakeven']:.1f}%" if te["breakeven"] is not None else "-"
        verdict = "YES" if te["qualifies"] else "no"
        print(f"{r['threshold']:>10.3f} | {tr['n']:>7} {tr_roi:>10} {tr_hit:>11} | {te['n']:>7} {te_roi:>9} {te_hit:>10} {ci_corr:>11} {breakeven:>10} {verdict:>10}")

    n_qualifying = sum(1 for r in results if r["test"]["qualifies"])
    print(
        f"\n{n_qualifying} of {n_thresholds} thresholds qualify under policy sections 1-4 "
        f"(min N={min_n}, Bonferroni-corrected CI clears breakeven, positive avg CLV).\n"
        "QUALIFIES=YES here means 'provisional' per policy section 5, not 'confirmed' — "
        "confirmation additionally requires 500+ bets and re-validation on a later, "
        "still-unseen window. A great TRAIN number with a non-qualifying TEST number "
        "is a warning sign, not a tiebreaker.\n"
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Walk-forward threshold optimizer")
    parser.add_argument("--edge", required=True)
    parser.add_argument("--train-frac", type=float, default=0.7)
    args = parser.parse_args()
    print_threshold_report(args.edge, train_frac=args.train_frac)
