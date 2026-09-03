# MLB Edge Lab

An automated pipeline for collecting daily MLB game/odds data, computing three
pre-defined "edge" signals, and tracking their historical ROI, CLV (closing
line value), and hit rate — for long-term statistical testing of betting-market
inefficiencies.

**This system does not predict winners and does not place bets.** It quantifies
gaps between simple statistical baselines (e.g. starting-pitcher xERA) and market
prices, logs what happened, and lets you query the results. Treat every ROI
number here as a hypothesis test, not a signal to act on — see "Statistical
Honesty" below.

## Easiest way to use this: the web dashboard (no typed commands)

1. **Add your API keys once.** Copy `.env.example` to `.env` and fill in your
   real keys (see "Setup" below for where to get them).
2. **Double-click to start:**
   - **Mac:** double-click `run_server.command`. If macOS blocks it the first
     time, right-click it → Open, then confirm.
   - **Windows:** double-click `run_server.bat`.
3. A browser tab opens automatically at `http://127.0.0.1:5050` with a
   dashboard: buttons for running the daily pipeline, viewing the Edge Board,
   and running the research tools (threshold optimizer, combination analyzer,
   Edge Score) — all clicks and forms, no terminal typing after this point.
4. **To stop it**, close the terminal window that opened (or press Ctrl+C in it).

This still runs real Python in the background — that's unavoidable, since the
system makes live API calls with secret keys and writes to a real database,
which a plain webpage can't do by itself. The double-click launcher is what
starts that background process for you; everything after that is buttons.

Screens available in the dashboard:
- **Dashboard** — initialize the database, run morning/closing/settle, enter
  final scores
- **Edge Board** — the daily signal table for any date
- **Research** — threshold optimizer, combination analyzer, Edge Score /
  qualified games, all-time summary
- **Policy** — the full `docs/qualification_policy.md` document, readable
  in-browser

If you'd rather use the command line directly, everything below still works
exactly as described — the dashboard is a thin layer on top of the same
`pipeline`/`reports`/`research` modules, not a separate system.

## What's included

```
mlb_edge_lab/
├── config.py              # env-based config, mock-mode toggle
├── main.py                # CLI orchestrator (morning/closing/settle/report)
├── run_server.command      # Mac double-click launcher for the web dashboard
├── run_server.bat          # Windows double-click launcher for the web dashboard
├── webapp/
│   └── app.py               # Flask dashboard — wraps pipeline/reports/research in a browser UI
├── db/
│   ├── schema.sql          # full relational schema
│   └── database.py         # sqlite connection + generic upsert helper
├── clients/
│   ├── sportsdataio.py     # SportsDataIO MLB API wrapper
│   ├── odds_api.py         # The Odds API wrapper
│   └── weather.py          # optional stadium weather enrichment
├── pipeline/
│   ├── ingest.py            # Step 1/2: pull + store games/odds/starters/weather
│   ├── edges.py             # Step 3: compute SP mismatch / bullpen fatigue / overreaction
│   └── evaluate.py          # Step 4: post-game ROI/CLV/hit-rate ledger
├── reports/
│   ├── edge_board.py         # Step 5: daily "MLB Edge Board" report
│   └── query_lab.py          # historical statistical-testing queries
├── requirements.txt
└── .env.example
```

## Setup

```bash
cd mlb_edge_lab
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your real API keys, then set MLB_EDGE_MOCK_MODE=false
```

Get keys from:
- SportsDataIO MLB API: https://sportsdata.io/developers/api-documentation/mlb (optional —
  games/starters/ERA now come from free public sources; see "Data sources" below)
- The Odds API: https://the-odds-api.com/ (required — sole odds source)

By default `MLB_EDGE_MOCK_MODE=true`, so the whole pipeline runs against
synthetic sample data with **zero API keys required** — good for verifying the
pipeline logic before spending API quota.

## ParlayAPI — second odds source (optional, not yet wired into the pipeline)

`clients/parlay_api.py` and a `PARLAY_API_KEY` slot on the Settings page
exist for **ParlayAPI** (https://parlay-api.com), added because it
documents a dedicated historical closing-odds endpoint
(`/v1/historical/sports/{sport}/closing-odds`) — a direct "give me the
actual closing line for this date" call, rather than the polling-plus-guard
approach `pipeline/ingest.py` currently uses with The Odds API (see
`_has_game_started()`). If it works as documented, it's a more reliable
foundation for CLV than polling ever can be.

**Status: built, but not yet verified against a real response, and not
yet wired into the daily pipeline.** ParlayAPI's public docs show request
examples (URLs, auth header) but not a full example response body, so
`clients/parlay_api.py` was written defensively — it guesses the response
shape based on ParlayAPI's "drop-in for the-odds-api" positioning, and
prints a diagnostic with the real response structure if that guess is
wrong, the same pattern used successfully for every other integration in
this project (SportsDataIO, ESPN, MLB Stats API all needed exactly one
round-trip against real data to nail down the exact field names).

**To verify it once you have a real key** (enter it on the Settings page
first):

```python
from clients.parlay_api import ParlayAPIClient
client = ParlayAPIClient()
odds = client.get_current_odds()
print(odds)
closing = client.get_closing_odds('2026-07-06')  # use a real past date
print(closing)
```

If that prints real event data, the shape guess was right and it's ready
to be wired into `pipeline/ingest.py` as either a second source or a
replacement for the closing-line step specifically. If it prints a
`[parlayapi] WARNING: ... response didn't match the expected shape`
diagnostic, paste that output back for a one-pass fix, same as every prior
integration in this project.

## The Odds API's free tier is credit-based, not request-based — read this before scheduling anything

The free tier is 500 **credits**/month, and each call costs `(number of
markets requested) x (number of regions)` credits — not 1 credit per call.
`clients/odds_api.py` requests moneyline (`h2h`) only by default, since none
of the three edge signals built so far use spreads or totals; that keeps
each call to 1 credit. If you ever add an edge that needs totals/spreads
and widen the `markets` parameter, every call gets proportionally more
expensive — worth knowing before flipping that back on.

At 1 credit/call: one morning call/day (~30 credits/month) leaves roughly
470 credits/month for closing-odds calls — about 15/day if spread evenly
across a month. `setup_closing_schedule.bat` (see below) defaults to
hourly, which uses about 13 calls across a typical game day, leaving a
safety margin for manual re-runs and testing.

## Automatic closing-odds fetching (Windows Task Scheduler)

MLB games on a given day start at different times (day games ~1pm ET,
night games up to ~10pm ET), so getting a real closing line for every game
means re-fetching odds several times throughout the day. This isn't
because the API stops returning a game once it starts — per The Odds
API's own docs, the `/odds` endpoint returns "upcoming, live and recently
completed games," so a live game's data keeps coming back. The reason
multiple fetches matter is the opposite problem: **once a game is live,
its moneyline reflects in-play win probability (shifts with the score),
not pregame closing sentiment** — so if you kept writing whatever the API
returns after a game starts, you'd silently overwrite a correct closing
line with contaminated in-play pricing. `pipeline/ingest.py`'s
`_has_game_started()` guards against exactly this: once a game's
commence_time has passed, its closing odds are left alone rather than
overwritten, no matter how many more times "closing" runs that day.

Rather than clicking the dashboard's "Run Closing" button repeatedly:

```
setup_closing_schedule.bat
```

Double-click once. This registers a Windows Task Scheduler job that runs
`python main.py closing --date today` automatically every hour from 11 AM
to 11 PM, every day — no window needs to stay open, no browser, nothing.
The last successful write before each individual game's actual start ends
up as its closing line, and every run after that for that game is a safe
no-op thanks to the started-game guard above.

To remove it later: `uninstall_closing_schedule.bat`.

**Known limitation:** Task Scheduler won't fire if your computer is asleep
at the scheduled time. If you want guaranteed coverage, either keep the
machine awake during game hours, or open Task Scheduler directly, find the
task, and check "Wake the computer to run this task" under its Conditions
tab (not something `schtasks` can set from the command line, has to be
done once in the GUI).

## Quick start (mock mode)

```bash
python main.py init                          # create tables
python main.py morning --date 2026-07-06     # ingest opening odds + compute edges + print report
python main.py closing --date 2026-07-06     # re-pull odds near first pitch (closing line)
python main.py settle  --date 2026-07-06     # after games finish, log ROI/CLV/hit-rate
python -m reports.query_lab summary          # all-time performance by edge type
```

## Daily operational flow

1. **Morning** (`main.py morning`): pull the day's schedule, probable starters,
   weather, and an "opening" odds snapshot. Compute edge signals from what's
   known pre-market-close.
2. **Closing** (`main.py closing`), run ~5–10 min before first pitch: re-pull
   odds as the "closing" snapshot, recompute edges (now with CLV inputs
   available).
3. **Settle** (`main.py settle`), after games finish: pull final scores,
   store outcomes, and log a row per fired edge signal into `edge_results`
   with win/loss, profit in flat units, and CLV%.

### Cron example

```cron
0 9  * * * cd /path/to/mlb_edge_lab && python main.py morning --date today >> logs/morning.log 2>&1
0 17 * * * cd /path/to/mlb_edge_lab && python main.py closing --date today >> logs/closing.log 2>&1
0 6  * * * cd /path/to/mlb_edge_lab && python main.py settle  --date yesterday >> logs/settle.log 2>&1
```

Note: `settle` currently expects you (or a small script you add) to call
`pipeline.evaluate.store_outcome(conn, game_id, home_score, away_score)` for
each finished game before `evaluate.run()` — this is left as an explicit,
reviewable step rather than auto-committing scores, since final-score field
names vary by SportsDataIO plan tier.

## The three edges

| Edge | What it measures | Output |
|---|---|---|
| **SP mismatch** | Gap between a naive xERA-based win probability and the market's implied probability | `sp_edge_score` (+ = model likes home more than market does) |
| **Bullpen fatigue** | Recent bullpen innings load + extra-innings flag per team | `bullpen_fatigue_index_{home,away}` |
| **Market overreaction** | Flags games where a team's last outing was a blowout (≥6 runs) and the line has since moved further in the "chase" direction | `overreaction_flag` / `overreaction_direction` |

All thresholds (xERA logistic scale, fatigue weights, blowout cutoff, line-move
threshold) are named constants at the top of `pipeline/edges.py` — tune them
there rather than hardcoding new magic numbers elsewhere.

## Querying history

```bash
python -m reports.query_lab roi --edge-type sp_mismatch --min-signal 0.075
python -m reports.query_lab roi --edge-type bullpen_fatigue
python -m reports.query_lab bullpen-underdogs --min-price 100
python -m reports.query_lab summary
```

Or query `edge_results` directly with SQL/pandas for anything more custom,
e.g. in a notebook:

```python
import pandas as pd, sqlite3
conn = sqlite3.connect("mlb_edge_lab.db")
df = pd.read_sql("SELECT * FROM edge_results", conn)
df.groupby("edge_type")["profit_units"].sum()
```

## Statistical honesty

- `query_lab` prints a warning whenever a sample is below 30 bets — small
  samples in sports betting are dominated by variance, not edge.
- These are backtests over a naive baseline model (a logistic mapping of xERA
  gap), not a validated predictive model. A positive-looking ROI over a small
  sample is not evidence of a durable inefficiency.
- CLV is a better early indicator than short-run ROI: consistently beating the
  closing line is the standard proxy sharp bettors use for "the signal has
  informational value," since it's harder to fake with variance than win/loss
  record over a few dozen games.
- None of this is financial or betting advice, and the system deliberately
  does not include a recommendation engine — only descriptive signals for you
  to evaluate.

## Extending

- **OpticOdds** (line movement / sharp money tracking): add `clients/opticodds.py`
  following the same pattern as `odds_api.py`; `OPTICODDS_API_KEY` is already
  wired into `config.py`.
- **Postgres**: swap `sqlite3.connect` in `db/database.py` for
  `psycopg2`/`SQLAlchemy`, adjust `AUTOINCREMENT` → `SERIAL` and
  `datetime('now')` → `NOW()` in `schema.sql`.
- **Full 30-team code map**: `pipeline/ingest.py::_team_to_code()` currently
  has a handful of teams stubbed in — fill out the rest for production use.

---

## Research layer (threshold optimization, combinations, Edge Score)

Once you have real settled games accumulating, the `research/` module turns
this from a fixed set of three hand-picked signals into a framework for
testing new ideas without touching the core pipeline.

```
research/
├── edge_registry.py            # plug-in registry — add new edges without editing core files
├── core_edges_adapter.py        # registers the original 3 edges as read-only adapters
├── data_loader.py                # rebuilds a threshold-agnostic dataset from settled games
├── threshold_optimizer.py       # walk-forward threshold grid search + Bonferroni-corrected qualification
├── combination_analyzer.py      # tests pairs of edges agreeing on the same side
├── edge_score.py                 # weighted composite score + game qualification
└── qualification_status.py      # Provisional/Confirmed status + decay-based downgrade

docs/
└── qualification_policy.md      # the fixed rules referenced by every module above
```

**`docs/qualification_policy.md` is the actual governing document** — every
numeric threshold in the modules above (min sample size, CI floor, CLV floor,
Bonferroni correction, Provisional vs Confirmed) implements a specific,
numbered section of that policy, not an arbitrary constant. Read it first;
it also documents the amendment process for changing any of these numbers
later (short version: not in response to a specific edge's current results).

### Adding a new edge (e.g. reverse line movement) without touching core files

```python
from research.edge_registry import register_edge

def compute_reverse_line_movement(conn, game_id):
    # your logic here — return None if not enough data
    return {"signal_value": 0.04, "side": "home"}

register_edge(
    name="reverse_line_movement",
    compute_fn=compute_reverse_line_movement,
    description="Line moves opposite the betting percentage",
    value_range=(0, 0.15),
)
```

Once registered, it's automatically picked up by the threshold optimizer,
combination scanner, and Edge Score engine — no other file needs to change.

### Threshold optimization (avoiding look-ahead bias)

```bash
python -m research.threshold_optimizer --edge sp_mismatch
```

This does **not** just search a grid and report the best number — it splits
games chronologically (train = older 70%, test = newer 30% by default) and
shows both. A threshold is only worth trusting if its test-window performance
resembles its train-window performance; a great train number with a falling-
apart test number is the signature of overfitting, not a signal to act on.
It also reports a 95% Wilson confidence interval on test hit-rate, and breaks
the test window into thirds to check for performance decay over time.

### Combination testing

```bash
python -m research.combination_analyzer --edge-a sp_mismatch --edge-b bullpen_fatigue \
    --threshold-a 0.08 --threshold-b 5.0
```

Reports each edge alone vs. both agreeing on the same side, train and test,
so you can see whether stacking signals actually adds anything over the
better individual edge — rather than assuming combinations help by default.
Combined sample sizes shrink fast (both signals must fire *and* agree), so
this flags when a combo's test N is too small to mean anything yet.

### Edge Score (weighted composite)

```bash
python -m research.edge_score --date 2026-07-06 --min-score 0.15
```

Weights each registered edge by its own out-of-sample ROI (never train-window
ROI, to avoid baking overfitting into the weights), normalizes each edge's
raw signal into 0–1 using its registered `value_range`, and sums the weighted
contributions per game. Edges with non-positive out-of-sample ROI get zero
weight — they cannot contribute noise or false confidence to the score.

**If every edge currently has non-positive out-of-sample ROI, every game
scores 0 and nothing qualifies.** That is the correct, honest output at low
sample sizes — not a bug to work around. Don't lower the bar until you
actually have evidence; let the "no qualified games today" result stand.

This is a ranking signal, not a probability or a stake-sizing recommendation.
The output of `qualify_games()` is a shortlist for you to review manually —
the architecture deliberately stops here. Automating actual bet placement
(e.g. against a specific sportsbook) is a separate concern this project does
not include, both because most sportsbooks' terms of service prohibit
automated/bot wagering, and because it's a bad idea to automate real-money
decisions off a system with only a few hundred games of history.

### Trying the research layer yourself before real data arrives

```bash
python tests/generate_synthetic_history.py   # 300 fake settled games
python3 -c "
from db.database import connection
from pipeline.edges import compute_edges_for_game
with connection() as conn:
    for gid in [r['game_id'] for r in conn.execute('SELECT game_id FROM games').fetchall()]:
        compute_edges_for_game(conn, gid)
"
python -m research.threshold_optimizer --edge sp_mismatch
python -m research.edge_score --date 2025-06-01 --min-score 0.05
```

This is a synthetic/demo dataset only — delete `mlb_edge_lab.db` and re-run
`main.py init` before pointing the system at real data, so fake games don't
mix with real ones.

### A note on the synthetic test run

While building this, I generated 300 fake games with a small, deliberately
weak true signal buried in noise, and ran all three tools against it end to
end. The threshold optimizer correctly showed train-window ROI looking
decent (~+3-5%) while test-window ROI was mostly negative — exactly what
overfitting to noise looks like. The Edge Score engine correctly assigned
**zero weight to all three edges** and qualified nothing, because none of
them had positive out-of-sample ROI on that synthetic run. That's the
system working as intended: with weak/no real signal, it should conclude
there's nothing to bet, not manufacture a confident-looking score anyway.
Real data will behave differently — this was just a plumbing check.
