"""
Scheduler / dispatcher.

Answers "when should something happen?" — never "how do we collect the
data?" (that's stage_registry.py). Reads stage definitions from
config/stages.yaml so adding a new stage never requires touching this
file.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import task_state
from stage_registry import HANDLERS

logger = logging.getLogger("orchestrator.scheduler")

STAGES_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "stages.yaml"


def load_config():
    with open(STAGES_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _parse_iso(ts):
    """Parses either 'YYYY-MM-DD HH:MM:SS' (sqlite datetime('now')) or
    full ISO8601 with 'Z'. Returns a naive UTC datetime for comparison."""
    ts = ts.replace("Z", "")
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _daily_pseudo_game_id(date_str):
    """daily_time stages aren't tied to a real game — use a synthetic
    game_id so they fit the same (game_id, stage_name) idempotency key
    as everything else, rather than needing a separate code path."""
    return f"DAILY-{date_str}"


def compute_due_stages(conn, cfg, now_utc):
    """Returns a list of dicts: {game_id, stage_name, handler, date_str,
    scheduled_time} for every stage that is due AND not already
    completed/running. This is the sole idempotency gate before
    dispatch — a stage already 'completed' or currently 'running' is
    never returned here again."""
    due = []
    today_str = now_utc.date().isoformat()
    now_local = datetime.now()  # naive local time — daily_time triggers are specified in local time (e.g. "06:00" = 6am on this machine), not UTC
    now_utc_naive = now_utc.replace(tzinfo=None)  # _parse_iso() below always returns naive datetimes, so this must match to be comparable

    for stage in cfg["stages"]:
        name = stage["name"]
        handler_name = stage["handler"]
        trigger = stage["trigger"]

        if trigger["type"] == "daily_time":
            hh, mm = trigger["at"].split(":")
            trigger_dt_local = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if now_local < trigger_dt_local:
                continue
            game_id = _daily_pseudo_game_id(today_str)
            run = task_state.get_run(conn, game_id, name)
            if run and run["status"] in ("completed", "running"):
                continue
            task_state.upsert_pending(conn, game_id, name, trigger_dt_local.isoformat())
            run = task_state.get_run(conn, game_id, name)
            if run["status"] == "failed":
                continue  # exhausted retries — needs manual attention, see Logs
            due.append({
                "game_id": game_id, "stage_name": name, "handler": handler_name,
                "date_str": today_str, "scheduled_time": trigger_dt_local.isoformat(),
                "run_id": run["id"], "attempt_number": run["attempt_number"],
            })

        elif trigger["type"] == "game_offset":
            offset_min = trigger["minutes_before_start"]
            games = conn.execute(
                """SELECT game_id, date, game_time_utc FROM games
                   WHERE game_time_utc IS NOT NULL
                     AND date >= ?
                     AND (status IS NULL OR status NOT IN ('final', 'postponed'))""",
                (today_str,),
            ).fetchall()
            for g in games:
                try:
                    game_dt = _parse_iso(g["game_time_utc"])
                except (ValueError, TypeError):
                    logger.warning(f"[scheduler] unparseable game_time_utc for {g['game_id']}, skipping")
                    continue
                scheduled_dt = game_dt - timedelta(minutes=offset_min)
                if now_utc_naive < scheduled_dt:
                    continue
                run = task_state.get_run(conn, g["game_id"], name)
                if run and run["status"] in ("completed", "running"):
                    continue
                task_state.upsert_pending(conn, g["game_id"], name, scheduled_dt.isoformat())
                run = task_state.get_run(conn, g["game_id"], name)
                if run["status"] == "failed":
                    continue
                due.append({
                    "game_id": g["game_id"], "stage_name": name, "handler": handler_name,
                    "date_str": g["date"], "scheduled_time": scheduled_dt.isoformat(),
                    "run_id": run["id"], "attempt_number": run["attempt_number"],
                })

    return due


def dispatch_due(conn, cfg, due_stages):
    """Groups due stages by (handler, date_str) so a shared whole-day
    ingest function (e.g. ingest_odds) is called once per group instead
    of once per game — see stage_registry.py docstring for why. Every
    game row in a group is marked completed/failed based on that single
    call's outcome."""
    retry_cfg = {s["name"]: s.get("retry", {}) for s in cfg["stages"]}

    groups = {}
    for item in due_stages:
        key = (item["handler"], item["date_str"], item["stage_name"])
        groups.setdefault(key, []).append(item)

    for (handler_name, date_str, stage_name), items in groups.items():
        handler = HANDLERS[handler_name]
        max_attempts = retry_cfg.get(stage_name, {}).get("attempts", 3)
        attempt_number = max(i["attempt_number"] for i in items) + 1

        for item in items:
            task_state.mark_running(conn, item["run_id"], attempt_number)
        conn.commit()

        try:
            task_state.with_lock_retry(
                lambda: handler(conn, date_str), logger=logger
            )
            conn.commit()
            for item in items:
                task_state.mark_completed(conn, item["run_id"])
                task_state.log_attempt(conn, item["game_id"], stage_name, attempt_number, "completed")
            conn.commit()
            logger.info(f"[scheduler] {stage_name} completed for {date_str} ({len(items)} game(s))")

        except Exception as e:
            conn.rollback()
            is_final = attempt_number >= max_attempts
            for item in items:
                task_state.mark_failed(conn, item["run_id"], str(e), attempt_number, final=is_final)
                task_state.log_attempt(conn, item["game_id"], stage_name, attempt_number, "failed", str(e))
            conn.commit()
            level = logger.error if is_final else logger.warning
            level(f"[scheduler] {stage_name} FAILED for {date_str} (attempt {attempt_number}/{max_attempts}): {e}")
