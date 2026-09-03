"""
Orchestrator process entry point.

Run standalone, separate from Flask:

    python orchestrator/runner.py

or via run_orchestrator.bat. Do not import this into the Flask app —
per the architecture decision, these are two independent processes
sharing one SQLite database in WAL mode.
"""
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # project root, for `import config`, `pipeline`, `db`

import config
from db.database import connection

sys.path.append(str(Path(__file__).resolve().parent))  # this dir, for `import task_state`, `import scheduler`
import task_state
import scheduler

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "orchestrator.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("orchestrator.runner")

_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.info(f"[runner] shutdown signal received ({signum}), finishing current cycle then exiting")
    _shutdown = True


def startup_checks():
    logger.info(f"[runner] starting up. DB_PATH={config.DB_PATH} MOCK_MODE={config.MOCK_MODE}")
    with connection() as conn:
        task_state.ensure_schema(conn)
        task_state.health_check(conn)
        recovered = task_state.recover_stale_running(conn, logger=logger)
        if recovered:
            logger.info(f"[runner] recovered {recovered} stale 'running' task(s) from a previous process")
    logger.info("[runner] startup checks passed: WAL active, required tables present")


def run_cycle():
    cfg = scheduler.load_config()
    with connection() as conn:
        due = scheduler.compute_due_stages(conn, cfg, datetime.now(timezone.utc))
        if due:
            logger.info(f"[runner] {len(due)} stage instance(s) due this cycle")
            scheduler.dispatch_due(conn, cfg, due)
        else:
            logger.debug("[runner] nothing due this cycle")
    return cfg.get("poll_interval_seconds", 60)


def main():
    signal.signal(signal.SIGINT, _handle_shutdown)
    try:
        signal.signal(signal.SIGTERM, _handle_shutdown)
    except (AttributeError, ValueError):
        pass  # SIGTERM not available on this platform (e.g. some Windows setups) — SIGINT/Ctrl+C still works

    startup_checks()

    while not _shutdown:
        try:
            interval = run_cycle()
        except Exception as e:
            logger.exception(f"[runner] unhandled error in cycle, will retry next poll: {e}")
            interval = 60

        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("[runner] shutdown complete")


if __name__ == "__main__":
    main()
