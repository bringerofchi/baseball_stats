# MLB Edge Lab

MLB Edge Lab is a Python and SQLite research pipeline for recording daily MLB market and game context, calculating defined signals, and evaluating their historical ROI, hit rate, and closing-line value (CLV). It does not place bets or claim to predict winners.

## Daily pipeline

`main.py` supports five subcommands — four daily-pipeline stages plus `init` for one-time schema setup:

1. `morning` ingests scheduled games, starters, weather, and opening moneylines; computes edges; and renders the Edge Board.
2. `closing` refreshes pregame prices, preserving the last valid pre-start snapshot as the closing record; recomputes edges; and renders the board.
3. `settle` fetches final results from the MLB Stats API for finished games, then evaluates qualifying signals. A manual outcome form remains only as a fallback.
4. `report` renders the board for a requested date.
5. `init` creates/initializes the SQLite schema; not part of the recurring daily cycle.

The Flask dashboard is a UI over the same pipeline, reports, and research modules.

## Core signals

The current core ledger has three intentionally simple signals:

- **Starting-pitcher mismatch:** a logistic mapping of the xERA gap compared with market implied probability.
- **Bullpen fatigue:** weighted bullpen workload over the previous three days, including extra-inning exposure.
- **Market overreaction:** a recent blowout plus a meaningful price movement in the direction of chasing that result.

These are hypotheses to test, not validated recommendations.

> **Current caveat:** the live ingest pipeline never populates `team_form` (0 rows in the current database), and no code path in `pipeline/ingest.py` writes to it — it's only ever filled by the test-only `tests/generate_synthetic_history.py` generator. Bullpen fatigue and market overreaction both depend on `team_form`, so neither has produced a qualifying `edge_results` row against real data: all 239 settled `edge_results` rows currently on record are `sp_mismatch`. Treat bullpen fatigue and market overreaction as implemented-but-currently-inert until `team_form` ingestion is wired up.

## Data model

`mlb_edge_lab.db` stores games, multi-book opening and closing moneylines, starters, team form, final outcomes, computed edges, and an idempotent `edge_results` ledger. Result rows retain side, taken and closing price, CLV, signal value, outcome, and flat-unit P&L.

The database is the project’s primary research artifact. Before drawing conclusions, inspect its real row counts, source coverage, missing closing lines, and percentage of settled edge rows. This README intentionally does not claim those counts without a current database extraction.

## Research safeguards

The research layer provides an edge registry, chronological train/test threshold analysis, Wilson intervals, performance-decay checks, combination analysis, and an out-of-sample-weighted Edge Score. Qualification policy is intentionally separate from any short-run result.

Small positive ROI is not proof of a durable edge. CLV is useful only where a genuine, timely closing price was captured. A legitimate output is “no qualified games.”

## Current limitations

- ParlayAPI is wired into the daily pipeline as an automatic fallback odds source (`pipeline/ingest.py`, used when `ODDS_SOURCE=auto` — the default — and The Odds API call fails), not an integration that sits outside the daily flow. What remains unverified is its response-shape handling: the client's own docstring notes the JSON structure isn't confirmed against a real ParlayAPI response.
- Data quality depends on source availability and coverage.
- The starter/xERA baseline is deliberately narrow; it is not a full game-projection model.
- This repository contains a database artifact, but its current live-versus-synthetic composition must be verified before it is described as accumulated production history.
- This directory is not a git repository (no `.git`), so `mlb_edge_lab.db` — the project's primary research artifact — has no version-control history or backup beyond the local file.
- A second, larger `README.md` also exists in this directory alongside this file; confirm which is canonical before relying on either for onboarding.

## Relationship to MLB Daily Edge Board

This is separate from `baseball_bets`. MLB Edge Lab is a Python/SQLite experimental ledger built around three defined signals and reproducible snapshots. `baseball_bets` is a browser-local, underdog-oriented daily card and bet tracker with different heuristics and storage.
