# Edge Qualification Policy

**Alpha Decision Engine — MLB Edge Lab module**
Version 1.0 — drafted before real data collection begins, per design intent.

## Purpose

This document defines the fixed, pre-committed rules by which a signal (an
individual edge, or a combination of edges) is allowed to be called
"qualified" — i.e., backed by enough historical evidence to warrant showing
up on the Edge Board as something worth a human's attention.

**The rule this document exists to serve: thresholds are set once, in
advance, and not renegotiated after looking at results.** The value of a
qualification policy comes entirely from it being fixed before the data that
would tempt you to bend it. Any change to the numbers below must go through
the amendment process in section 6 — not a quiet edit.

If nothing qualifies, "nothing qualifies" is the correct output. A system
that always finds something to recommend is not measuring evidence; it's
measuring how hard it's being asked to look.

---

## 1. Minimum sample size

| Requirement | Threshold |
|---|---|
| Minimum out-of-sample (test-window) bets before an edge is scored at all | **50** |
| Minimum out-of-sample bets before an edge can carry nonzero weight in the Edge Score | **50** |
| Minimum out-of-sample bets before a *combination* of edges can qualify | **30** |
| Minimum out-of-sample bets before any conclusion is treated as "confirmed" rather than "provisional" | **100** |

Rationale: combinations naturally accumulate slower (both signals must fire
and agree), so a lower bar is used there or nothing would ever accumulate
enough history to test. But even 30 is closer to a first read than a
confirmed finding — see the "provisional vs. confirmed" language in section
5.

This is deliberately below your own stated target of 500–1,000 games before
drawing major conclusions. The numbers above are the floor for a signal to
appear on the board at all, not the bar for treating it as validated. Section
5 keeps those two ideas separate.

## 2. Statistical significance — confidence interval floor

An edge or combination qualifies only if **the lower bound of its 95% Wilson
confidence interval on hit rate is above the breakeven hit rate implied by
the average odds taken.**

Example: if the average odds taken on the qualifying bets is -110 (52.4%
breakeven), the edge must show a lower CI bound above 52.4%, not just a point
estimate above it. A point estimate of 55% with a CI of [47%, 63%] does not
qualify — the interval straddles breakeven, meaning the data can't rule out
"no edge" yet.

This is already implemented in `research/threshold_optimizer.py`
(`wilson_interval()`); the policy here is to actually gate on it rather than
just display it.

## 3. Closing Line Value (CLV) floor

An edge or combination qualifies only if **average CLV across its
out-of-sample bets is positive (> 0%).**

Rationale: CLV is a better early indicator than short-run ROI because it's
harder to fake with variance. A signal with a positive record but negative
average CLV is more likely a variance run than a real edge, and should not
qualify even if its win-loss record currently looks fine. If ROI and CLV
disagree, CLV is the tie-breaker for qualification; ROI is still reported for
context.

## 4. Multiple-comparisons guard

The threshold optimizer tests a grid (e.g. 10+ thresholds per edge), and the
combination analyzer tests every pair. Testing many thresholds/combinations
and reporting only the best-looking one is a classic way to manufacture a
false positive — some threshold will look great by chance alone even with
zero real edge, purely because enough of them were tried.

Policy:
- When scanning a grid of **N** thresholds for one edge, the CI floor in
  section 2 must be met at a Bonferroni-corrected confidence level of
  `1 - (0.05 / N)`, not the naive 95%. In practice this means: if you test 10
  thresholds, use roughly a 99.5% CI, not 95%, before letting any single one
  of them qualify.
- When scanning all pairwise combinations, the same correction applies across
  the number of pairs actually tested.
- **Implemented** in `research/threshold_optimizer.py` — `optimize_threshold()`
  applies `bonferroni_confidence(0.95, len(grid))` across the full scanned
  grid and reports both the corrected CI lower bound and a per-threshold
  QUALIFIES verdict. `research/qualification_status.py` accepts a
  `num_comparisons` argument so a threshold chosen from a 10-value grid is
  evaluated at the same corrected level it was selected under, not a fresh
  uncorrected 95%.

## 5. Provisional vs. confirmed status

Every qualifying edge carries one of two statuses, always shown alongside it:

- **Provisional** — clears sections 1–4 at their minimum thresholds (30–100
  bets). Can appear on the Edge Board as "worth watching." Not a
  recommendation.
- **Confirmed** — clears sections 1–4 AND has at least 500 out-of-sample
  bets AND has been re-validated on a subsequent, later out-of-sample window
  that it was not fit or threshold-searched against (i.e. tested against
  data collected *after* the threshold was chosen, not just held out from
  data collected before). Only "Confirmed" edges are eligible to be labeled
  a recommendation rather than a research finding.

**Implemented** in `research/qualification_status.py` — `classify_status()`
approximates the "later, still-unseen window" requirement via the trailing
100 out-of-sample bets rather than a third data split (a third split would
shrink an already-scarce out-of-sample set too far to be useful). This is a
simplification worth revisiting once real volume is high enough to afford a
proper three-way split (train / threshold-selection / confirmation).

This distinction exists because "qualifies on paper" and "held up when tested
against data that came later" are different claims, and the platform's
long-term credibility depends on not collapsing them into one badge.

## 6. Decay monitoring

A **Confirmed** edge is automatically downgraded back to **Provisional** if
either:
- Its trailing 100-bet ROI turns negative, or
- Its trailing 100-bet average CLV turns negative,

whichever triggers first. `research/threshold_optimizer.py`'s decay-check
(three-way split of the test window) is the mechanism for the descriptive
view of this; `research/qualification_status.py`'s `classify_status()` is
the mechanism that actually enforces the downgrade, since it always
re-derives status from current data on every call rather than reading a
stored label — there is no persisted "Confirmed" badge that can go stale.

## 7. Amendment process

Any change to the numeric thresholds in sections 1–4 requires:
1. A written note of what's changing and why, dated and kept in this
   document's revision history (below).
2. The change must not be motivated by a specific edge's current results —
   i.e. "edge X almost qualifies, let's lower the bar" is exactly the failure
   mode this document exists to prevent, and is an explicit disqualifying
   reason for a change.
3. Acceptable reasons to amend: new statistical technique that's more
   rigorous than what's here now, a genuine error found in the current
   methodology, or a deliberate, pre-registered decision to loosen/tighten
   standards for a new sport with different bet volume characteristics.

## 8. What this policy does not cover

- Bet sizing / bankroll management — out of scope for this document and for
  the platform as currently designed (see prior notes on stopping at
  "qualified shortlist" rather than automating stakes or placement).
- Which specific sportsbook to bet at, or automated bet placement — not part
  of this platform.
- Non-MLB sports — this version is written against the MLB Edge Lab's schema
  and tooling; a multi-sport version will need sport-specific breakeven/vig
  conventions revisited (e.g. run line vs. point spread hold percentages).

---

## Revision history

| Version | Date | Change | Reason |
|---|---|---|---|
| 1.0 | Drafted pre-data-collection | Initial policy | Establish fixed rules before real ROI numbers exist, per design intent |
