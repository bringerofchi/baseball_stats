"""
Stage handlers: the "how do we collect the data" layer.

Each handler wraps an existing pipeline.ingest function unchanged — no
Edge Lab logic is touched here. A handler's only orchestrator-specific
job is to (1) call the real ingest function and (2) stamp provenance
columns on whatever rows it touched.

Handlers take (conn, date_str) and return nothing on success, or raise
on failure — scheduler.py handles retry/backoff around whatever a
handler raises.

Note: pipeline.ingest's functions operate on a whole day's slate, not a
single game, because that's how the existing MLB Edge Lab pipeline is
built (see ingest.py). Rather than rewriting those functions to be
per-game, the scheduler groups due per-game stages by (date, handler)
and calls the handler once per group — see scheduler.py:_dispatch_due.
"""
from datetime import datetime, timezone

from pipeline import edges, ingest
from task_state import DATA_VERSION


def _stamp_provenance(conn, table, date_str, source, stage_name):
    """Best-effort provenance stamp: sets the provenance columns on rows
    from `table` matching this date_str that don't have a provenance
    stamp yet from *this* run. Uses a wide UPDATE rather than tracking
    exact row ids, since ingest.py's functions don't return which rows
    they touched — acceptable because collection_stage naturally
    reflects "the last stage that touched this row," which is the
    useful provenance question."""
    now = datetime.now(timezone.utc).isoformat()
    if table == "games":
        conn.execute(
            """UPDATE games SET data_source=?, timestamp_collected=?,
               collection_stage=?, data_version=?, collection_status='ok'
               WHERE date=?""",
            (source, now, stage_name, DATA_VERSION, date_str),
        )
    elif table in ("odds", "starters", "edges"):
        conn.execute(
            f"""UPDATE {table} SET data_source=?, timestamp_collected=?,
                collection_stage=?, data_version=?, collection_status='ok'
                WHERE game_id IN (SELECT game_id FROM games WHERE date=?)""",
            (source, now, stage_name, DATA_VERSION, date_str),
        )


def sync_daily_schedule(conn, date_str):
    """Discovers the day's games. Must run before any game_offset stage
    can be scheduled, since those depend on games.game_time_utc existing."""
    ingest.ingest_games(conn, date_str)
    _stamp_provenance(conn, "games", date_str, "mlb_stats_api", "daily_schedule_sync")


def odds_opening_snapshot(conn, date_str):
    ingest.ingest_odds(conn, date_str, snapshot="opening")
    _stamp_provenance(conn, "odds", date_str, "odds_pipeline_auto", "odds_opening_snapshot")


def odds_closing_snapshot(conn, date_str):
    ingest.ingest_odds(conn, date_str, snapshot="closing")
    _stamp_provenance(conn, "odds", date_str, "odds_pipeline_auto", "closing_snapshot")


def starter_refresh(conn, date_str):
    ingest.ingest_starters(conn, date_str)
    _stamp_provenance(conn, "starters", date_str, "mlb_stats_api", "starter_refresh")


def weather_refresh(conn, date_str):
    games = ingest.MLBStatsAPIClient().get_schedule(date_str)
    ingest.ingest_weather(conn, games, date_str)
    _stamp_provenance(conn, "games", date_str, "weather_api", "weather_refresh")


def compute_edges(conn, date_str):
    """Computes sp_mismatch (and any other active) edge signals from the
    latest starter + market snapshot data for this date. This is the same
    function the dashboard's manual 'Compute Edges' button calls
    (pipeline.edges.run) — wiring it in here as a stage just means it now
    also runs automatically instead of depending on someone clicking it.

    Note: edges.run() manages its own DB connection internally (it opens
    a fresh `with connection() as conn:` block rather than accepting one),
    unlike every other handler in this file. So — unlike odds/starters/
    weather above — we deliberately do NOT pass this handler's `conn`
    into edges.run(). We only reuse `conn` afterward for the provenance
    stamp, which runs as a separate short transaction against the rows
    edges.run() just wrote. Safe under WAL mode, consistent with the
    project's "short transactions, no held-open connections across calls"
    pattern.

    Registered twice in stages.yaml under different stage names
    (edge_computation, edge_recomputation_final) pointing at this same
    handler: once on the market_update cadence so edges track line
    movement, and once right after final_starter_check so a late
    scratch gets reflected before first pitch instead of scoring against
    a stale probable starter."""
    edges.run(date_str)
    _stamp_provenance(conn, "edges", date_str, "edge_lab_scoring", "compute_edges")


HANDLERS = {
    "sync_daily_schedule": sync_daily_schedule,
    "odds_opening_snapshot": odds_opening_snapshot,
    "odds_closing_snapshot": odds_closing_snapshot,
    "starter_refresh": starter_refresh,
    "weather_refresh": weather_refresh,
    "compute_edges": compute_edges,
}
