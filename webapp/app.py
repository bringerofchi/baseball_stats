"""
MLB Edge Lab — Web Dashboard

A local web UI wrapping the existing pipeline/reports/research modules so
day-to-day use is buttons in a browser instead of typed commands.

What this does NOT change: this still needs Python running in the
background, because it makes real API calls with secret keys and writes to
a real database — that's not something a plain webpage can do on its own.
What it DOES change: starting it is one double-click (see run_server.command
/ run_server.bat in the project root), and every day-to-day action after
that — running the morning pipeline, viewing the Edge Board, running
research tools — is a button, not a command.

Run directly with `python3 webapp/app.py` (or via the launcher scripts),
then open http://127.0.0.1:5050 — it also tries to open that automatically.
"""
import contextlib
import io
import sys
import threading
import webbrowser
from datetime import date, timedelta

sys.path.append(".")

from flask import Flask, request, redirect, url_for

from db.database import init_db
from pipeline import ingest, edges as edges_module, evaluate
from reports import edge_board, query_lab
from research import threshold_optimizer, combination_analyzer, edge_score
from research.edge_registry import list_edges
import research.core_edges_adapter  # noqa: F401 — registers sp_mismatch/bullpen_fatigue/overreaction

app = Flask(__name__)

PORT = 5050


def capture_output(fn, *args, **kwargs):
    """Runs fn and captures whatever it print()s, since all the existing
    pipeline/report/research modules are written as print-based CLI tools.
    Wrapping stdout is much less code than rewriting every module to return
    strings, and keeps this dashboard a thin layer over already-tested code.

    Also appends the captured output to the shared log file (see
    logging_setup.py) so it's still available later from the Logs page,
    not just on this one response page."""
    from logging_setup import append_to_log

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(*args, **kwargs)
    except Exception as e:
        buf.write(f"\n[ERROR] {type(e).__name__}: {e}\n")
    output = buf.getvalue()
    label = f"dashboard: {getattr(fn, '__module__', '')}.{getattr(fn, '__name__', fn)} {args}"
    append_to_log(output, label=label)
    return output


def page(title: str, body: str, active: str = ""):
    nav_items = [
        ("dashboard", "Dashboard", url_for("dashboard")),
        ("edge_board", "Edge Board", url_for("view_edge_board")),
        ("research", "Research", url_for("research_home")),
        ("policy", "Policy", url_for("view_policy")),
        ("logs", "Logs", url_for("view_logs")),
        ("settings", "Settings", url_for("view_settings")),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="navlink{" active" if key == active else ""}">{label}</a>'
        for key, label, href in nav_items
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title} — MLB Edge Lab</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
          max-width: 960px; margin: 0 auto; padding: 24px; color: #1a1a2e; background: #fafafa; }}
  h1 {{ font-size: 1.6em; margin-bottom: 4px; }}
  .subtitle {{ color: #666; margin-top: 0; margin-bottom: 20px; }}
  nav {{ margin-bottom: 24px; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }}
  .navlink {{ margin-right: 20px; text-decoration: none; color: #444; font-weight: 500; }}
  .navlink.active {{ color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
  .card {{ background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
  .card h2 {{ margin-top: 0; font-size: 1.15em; }}
  button, input[type=submit] {{ background: #1a73e8; color: white; border: none; padding: 8px 16px;
          border-radius: 5px; cursor: pointer; font-size: 0.95em; }}
  button:hover, input[type=submit]:hover {{ background: #1558b0; }}
  input[type=text], input[type=number], select {{ padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; }}
  pre {{ background: #1e1e2e; color: #d4d4d4; padding: 16px; border-radius: 6px; overflow-x: auto;
         font-size: 0.85em; line-height: 1.4; }}
  .warn {{ background: #fff3cd; border: 1px solid #ffe69c; padding: 12px; border-radius: 6px; margin-bottom: 16px; }}
  form.inline {{ display: inline; }}
  .row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }}
  a {{ color: #1a73e8; }}
</style>
</head>
<body>
<h1>MLB Edge Lab</h1>
<p class="subtitle">Alpha Decision Engine — research dashboard</p>
<nav>{nav_html}</nav>
{body}
</body>
</html>"""


def today():
    return date.today().isoformat()


def yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


# --------------------------------------------------------------------------
# Dashboard — the daily buttons: init / morning / closing / settle
# --------------------------------------------------------------------------

@app.route("/")
def dashboard():
    import config
    mode_note = (
        '<div class="warn"><strong>Mock mode is ON</strong> — everything below runs against '
        "synthetic sample data, not real games. Set MLB_EDGE_MOCK_MODE=false in your .env "
        "file (and add real API keys) to switch to live data.<br><br>"
        f"Database file in use: <code>{config.DB_PATH}</code></div>"
        if config.MOCK_MODE else
        '<div class="card" style="background:#e6f4ea;"><strong>Mock mode is OFF</strong> — running against live APIs.<br><br>'
        f"Database file in use: <code>{config.DB_PATH}</code></div>"
    )

    body = f"""
{mode_note}
<div class="card">
  <h2>1. Set up database (one-time)</h2>
  <form method="post" action="{url_for('run_action', step='init')}">
    <button type="submit">Initialize Database</button>
  </form>
</div>

<div class="card">
  <h2>2. Daily pipeline</h2>
  <form method="post" action="{url_for('run_action', step='morning')}" class="row">
    <label>Date: <input type="text" name="date" value="{today()}" size="12"></label>
    <button type="submit">Run Morning (ingest + compute edges)</button>
  </form>
  <form method="post" action="{url_for('run_action', step='closing')}" class="row">
    <label>Date: <input type="text" name="date" value="{today()}" size="12"></label>
    <button type="submit">Run Closing (re-pull odds near first pitch)</button>
  </form>
  <form method="post" action="{url_for('run_action', step='settle')}" class="row">
    <label>Date: <input type="text" name="date" value="{yesterday()}" size="12"></label>
    <button type="submit">Run Settle (auto-fetches final scores + logs ROI/CLV)</button>
  </form>
  <p style="color:#666; font-size:0.9em;">Settle automatically pulls final scores from MLB Stats
  API for any finished games — no manual entry needed for the normal case. Games not yet final
  are skipped (not an error); re-run Settle later in the day to pick them up.</p>
</div>

<div class="card">
  <h2>3. Manual score entry (fallback only)</h2>
  <p style="color:#666; font-size:0.9em;">Settle above handles this automatically for almost every
  game. Only use this if Settle's log shows a game marked Final with no extractable score.</p>
  <form method="post" action="{url_for('store_outcome_action')}" class="row">
    <input type="text" name="game_id" placeholder="game_id" size="10" required>
    <input type="number" name="home_score" placeholder="home score" size="6" required>
    <input type="number" name="away_score" placeholder="away score" size="6" required>
    <button type="submit">Store Outcome</button>
  </form>
  <p style="color:#666; font-size:0.9em;">Find game_id values on the Edge Board page.</p>
</div>
"""
    return page("Dashboard", body, active="dashboard")


@app.route("/run/<step>", methods=["POST"])
def run_action(step):
    d = request.form.get("date", today())
    if step == "init":
        output = capture_output(init_db)
    elif step == "morning":
        output = capture_output(ingest.run, d, "opening")
        output += capture_output(edges_module.run, d)
    elif step == "closing":
        output = capture_output(ingest.run, d, "closing")
        output += capture_output(edges_module.run, d)
    elif step == "settle":
        output = capture_output(evaluate.run, d)
    else:
        output = f"Unknown step: {step}"

    body = f"""
<div class="card">
  <h2>Result: {step} ({d})</h2>
  <pre>{_escape(output)}</pre>
  <a href="{url_for('dashboard')}">&larr; Back to Dashboard</a>
  &nbsp;|&nbsp;
  <a href="{url_for('view_edge_board', date=d)}">View Edge Board for {d} &rarr;</a>
</div>
"""
    return page(f"Ran {step}", body, active="dashboard")


@app.route("/store-outcome", methods=["POST"])
def store_outcome_action():
    from db.database import connection
    from pipeline.evaluate import store_outcome
    game_id = request.form.get("game_id")
    home_score = int(request.form.get("home_score"))
    away_score = int(request.form.get("away_score"))

    def _do():
        with connection() as conn:
            winner = store_outcome(conn, game_id, home_score, away_score)
            print(f"Stored outcome for {game_id}: {home_score}-{away_score}, winner={winner}")

    output = capture_output(_do)
    body = f"""
<div class="card">
  <h2>Outcome stored</h2>
  <pre>{_escape(output)}</pre>
  <a href="{url_for('dashboard')}">&larr; Back to Dashboard</a>
</div>
"""
    return page("Outcome stored", body, active="dashboard")


# --------------------------------------------------------------------------
# Edge Board
# --------------------------------------------------------------------------

@app.route("/edge-board")
def view_edge_board():
    d = request.args.get("date", today())
    output = capture_output(edge_board.generate, d)
    body = f"""
<div class="card">
  <h2>Edge Board</h2>
  <form method="get" class="row">
    <label>Date: <input type="text" name="date" value="{d}" size="12"></label>
    <input type="submit" value="View">
  </form>
  <pre>{_escape(output)}</pre>
</div>
"""
    return page("Edge Board", body, active="edge_board")


# --------------------------------------------------------------------------
# Research tools
# --------------------------------------------------------------------------

@app.route("/research")
def research_home():
    edge_names = [e.name for e in list_edges()]
    edge_options = "".join(f'<option value="{n}">{n}</option>' for n in edge_names)

    body = f"""
<div class="card">
  <h2>Threshold Optimizer</h2>
  <p style="color:#666; font-size:0.9em;">Walk-forward grid search with Bonferroni-corrected qualification (see Policy tab).</p>
  <form method="get" action="{url_for('research_threshold')}" class="row">
    <select name="edge">{edge_options}</select>
    <input type="submit" value="Run">
  </form>
</div>

<div class="card">
  <h2>Combination Analyzer</h2>
  <form method="get" action="{url_for('research_combo')}" class="row">
    <select name="edge_a">{edge_options}</select>
    <select name="edge_b">{edge_options}</select>
    <input type="text" name="threshold_a" placeholder="threshold A" value="0.06" size="8">
    <input type="text" name="threshold_b" placeholder="threshold B" value="3.0" size="8">
    <input type="submit" value="Run">
  </form>
</div>

<div class="card">
  <h2>Edge Score / Qualified Games</h2>
  <form method="get" action="{url_for('research_qualify')}" class="row">
    <label>Date: <input type="text" name="date" value="{today()}" size="12"></label>
    <label>Min score: <input type="text" name="min_score" value="0.15" size="6"></label>
    <input type="submit" value="Run">
  </form>
</div>

<div class="card">
  <h2>All-Time Summary</h2>
  <form method="get" action="{url_for('research_summary')}">
    <input type="submit" value="View Summary">
  </form>
</div>
"""
    return page("Research", body, active="research")


@app.route("/research/threshold")
def research_threshold():
    edge = request.args.get("edge", "sp_mismatch")
    output = capture_output(threshold_optimizer.print_threshold_report, edge)
    body = f"""<div class="card"><h2>Threshold Optimization: {edge}</h2><pre>{_escape(output)}</pre>
    <a href="{url_for('research_home')}">&larr; Back to Research</a></div>"""
    return page("Threshold Optimizer", body, active="research")


@app.route("/research/combo")
def research_combo():
    a = request.args.get("edge_a", "sp_mismatch")
    b = request.args.get("edge_b", "bullpen_fatigue")
    ta = float(request.args.get("threshold_a", 0.06))
    tb = float(request.args.get("threshold_b", 3.0))
    output = capture_output(combination_analyzer.print_pair_report, a, b, ta, tb)
    body = f"""<div class="card"><h2>Combination: {a} + {b}</h2><pre>{_escape(output)}</pre>
    <a href="{url_for('research_home')}">&larr; Back to Research</a></div>"""
    return page("Combination Analyzer", body, active="research")


@app.route("/research/qualify")
def research_qualify():
    d = request.args.get("date", today())
    min_score = float(request.args.get("min_score", 0.15))
    output = capture_output(edge_score.print_qualification_report, d, min_score)
    body = f"""<div class="card"><h2>Qualified Games — {d}</h2><pre>{_escape(output)}</pre>
    <a href="{url_for('research_home')}">&larr; Back to Research</a></div>"""
    return page("Edge Score", body, active="research")


@app.route("/research/summary")
def research_summary():
    output = capture_output(query_lab.summary_report)
    body = f"""<div class="card"><h2>All-Time Summary</h2><pre>{_escape(output)}</pre>
    <a href="{url_for('research_home')}">&larr; Back to Research</a></div>"""
    return page("Summary", body, active="research")


# --------------------------------------------------------------------------
# Policy doc viewer
# --------------------------------------------------------------------------

@app.route("/policy")
def view_policy():
    try:
        with open("docs/qualification_policy.md") as f:
            content = f.read()
    except FileNotFoundError:
        content = "docs/qualification_policy.md not found."
    body = f"""<div class="card"><h2>Edge Qualification Policy</h2><pre>{_escape(content)}</pre></div>"""
    return page("Policy", body, active="policy")


@app.route("/logs")
def view_logs():
    """Shows the tail of logs/mlb_edge_lab.log — this is where output from
    EVERY run ends up, including the closing-odds Task Scheduler job that
    runs in the background with no visible console of its own. Look here
    for lines like '[ingest] odds source for this run: ...' or
    '[ingest] NOTE: ... unmatched' after any run, scheduled or manual."""
    from logging_setup import read_recent_log, LOG_FILE

    content = read_recent_log()
    body = f"""<div class="card">
  <h2>Recent Log Output</h2>
  <p style="color:#666; font-size:0.9em;">Showing the most recent output from
  <code>{_escape(str(LOG_FILE))}</code> — every run writes here, including the
  background closing-odds task, so this is the place to check after the fact
  for which odds source ran or which games didn't match.</p>
  <a href="{url_for('view_logs')}"><button type="button">Refresh</button></a>
  <pre>{_escape(content)}</pre>
</div>"""
    return page("Logs", body, active="logs")


# --------------------------------------------------------------------------
# Settings — API keys and config, editable from the browser instead of .env
# --------------------------------------------------------------------------

@app.route("/settings")
def view_settings():
    from webapp.env_manager import get_current_values
    v = get_current_values()
    mock_checked = "checked" if v["MLB_EDGE_MOCK_MODE"] == "true" else ""

    body = f"""
<div class="card">
  <h2>API Keys &amp; Settings</h2>
  <p style="color:#666; font-size:0.9em;">Saved directly to your local <code>.env</code> file —
  no need to edit it by hand. These are stored in plain text on your own computer; don't share
  this file or share your screen while these are visible.</p>
  <form method="post" action="{url_for('save_settings')}">
    <table style="border-collapse: collapse; width: 100%;">
      <tr><td style="padding:6px 8px 6px 0;">SportsDataIO API key</td>
          <td><input type="text" name="SPORTSDATAIO_API_KEY" value="{_escape(v['SPORTSDATAIO_API_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">The Odds API key</td>
          <td><input type="text" name="ODDS_API_KEY" value="{_escape(v['ODDS_API_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">Live odds source</td>
          <td><select name="ODDS_SOURCE">
                <option value="auto" {"selected" if v["ODDS_SOURCE"] == "auto" else ""}>Auto (Odds API -> ParlayAPI -> SharpAPI)</option>
                <option value="odds_api" {"selected" if v["ODDS_SOURCE"] == "odds_api" else ""}>The Odds API only</option>
                <option value="parlay_api" {"selected" if v["ODDS_SOURCE"] == "parlay_api" else ""}>ParlayAPI only</option>
                <option value="sharpapi" {"selected" if v["ODDS_SOURCE"] == "sharpapi" else ""}>SharpAPI only</option>
              </select>
              <div style="color:#999; font-size:0.85em; margin-top:4px;">
                Set to a specific source while The Odds API credits are exhausted, or leave on
                "Auto" to switch over automatically the moment a call fails.
              </div></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">OpticOdds API key <span style="color:#999;">(optional, future use)</span></td>
          <td><input type="text" name="OPTICODDS_API_KEY" value="{_escape(v['OPTICODDS_API_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">Weather API key <span style="color:#999;">(optional)</span></td>
          <td><input type="text" name="WEATHER_API_KEY" value="{_escape(v['WEATHER_API_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">ParlayAPI key <span style="color:#999;">(optional, second odds source)</span></td>
          <td><input type="text" name="PARLAY_API_KEY" value="{_escape(v['PARLAY_API_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">SharpAPI key <span style="color:#999;">(optional, third odds source/fallback)</span></td>
          <td><input type="text" name="SHARPAPI_KEY" value="{_escape(v['SHARPAPI_KEY'])}"
              style="width:100%; max-width:420px;"></td></tr>
      <tr><td style="padding:12px 8px 6px 0;">Mock mode</td>
          <td style="padding-top:12px;"><label><input type="checkbox" name="MLB_EDGE_MOCK_MODE"
              value="true" {mock_checked}> Use synthetic sample data instead of live APIs</label></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">Odds regions</td>
          <td><input type="text" name="ODDS_API_REGIONS" value="{_escape(v['ODDS_API_REGIONS'])}" size="10"></td></tr>
      <tr><td style="padding:6px 8px 6px 0;">Odds bookmakers filter <span style="color:#999;">(optional, comma-separated)</span></td>
          <td><input type="text" name="ODDS_API_BOOKMAKERS" value="{_escape(v['ODDS_API_BOOKMAKERS'])}"
              style="width:100%; max-width:420px;"></td></tr>
    </table>
    <br>
    <button type="submit">Save Settings</button>
  </form>
</div>
<div class="card">
  <h2>Get API keys</h2>
  <p>SportsDataIO (no longer required — games/starters/ERA now come from free public sources,
  but kept here in case you use it for something else later):
  <a href="https://sportsdata.io" target="_blank">sportsdata.io</a></p>
  <p>The Odds API (primary odds source):
  <a href="https://the-odds-api.com" target="_blank">the-odds-api.com</a></p>
  <p>ParlayAPI (second odds source — used for closing-line cross-checks, and now also
  usable as a live-odds fallback via the "Live odds source" setting above when The Odds
  API is out of credits): <a href="https://parlay-api.com" target="_blank">parlay-api.com</a></p>
  <p>SharpAPI (<a href="https://sharpapi.io" target="_blank">sharpapi.io</a>, docs at
  <a href="https://docs.sharpapi.io" target="_blank">docs.sharpapi.io</a>) — third odds source,
  usable via the "Live odds source" setting above. Free tier covers DraftKings + FanDuel only.</p>
</div>
"""
    return page("Settings", body, active="settings")


@app.route("/settings/save", methods=["POST"])
def save_settings():
    from webapp.env_manager import save_values
    save_values(dict(request.form))
    body = f"""
<div class="card" style="background:#e6f4ea;">
  <h2>Settings saved</h2>
  <p>Your .env file has been updated and the dashboard has reloaded the new settings —
  no restart needed.</p>
  <a href="{url_for('dashboard')}">&larr; Back to Dashboard</a>
  &nbsp;|&nbsp;
  <a href="{url_for('view_settings')}">Back to Settings</a>
</div>
"""
    return page("Settings saved", body, active="settings")


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    threading.Timer(1.0, _open_browser).start()
    print(f"\nMLB Edge Lab dashboard starting at http://127.0.0.1:{PORT}")
    print("Leave this window open while using the dashboard. Close it (or Ctrl+C) to stop.\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
