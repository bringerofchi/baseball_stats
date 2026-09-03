"""
Shared file-logging helper.

Why this exists: nothing in this project previously wrote output anywhere
persistent. Manual runs (run_server.bat, double-clicking main.py) print to
whatever console window is open — fine as long as you keep that window and
scroll back far enough. But the closing-odds Task Scheduler job
(setup_closing_schedule.bat) runs main.py in the background with no console
at all, so that output had nowhere to go and was effectively lost. That
made it impossible to answer "which odds source did this run use?" or "did
any games fail to match?" after the fact.

This module gives every entry point (main.py CLI/scheduled runs, and the
dashboard's capture_output()) a single shared log file at
logs/mlb_edge_lab.log, viewable from the dashboard's Logs page without
needing to find the file manually.
"""
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "mlb_edge_lab.log"

# Keep the file from growing forever on an unattended machine.
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB


class _Tee:
    """Writes to multiple streams at once (e.g. real console + log file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def _rotate_if_needed():
    LOG_DIR.mkdir(exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
        LOG_FILE.rename(LOG_DIR / "mlb_edge_lab.log.old")


def append_to_log(text: str, label: str = ""):
    """Appends already-captured output (e.g. from the dashboard's
    capture_output()) to the shared log file, with a timestamp header."""
    _rotate_if_needed()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 70}\n[{datetime.now().isoformat(timespec='seconds')}] {label}\n{'=' * 70}\n")
        f.write(text)


def logged_run(label: str, fn, *args, **kwargs):
    """For CLI/scheduled entry points (main.py): runs fn with stdout/stderr
    mirrored to both the real console (if any) and the shared log file, so
    Task Scheduler runs — which have no visible console — still leave a
    record. Manual double-click runs still see everything live in the
    console window, same as before."""
    _rotate_if_needed()
    with open(LOG_FILE, "a", encoding="utf-8") as log_fh:
        log_fh.write(f"\n{'=' * 70}\n[{datetime.now().isoformat(timespec='seconds')}] {label}\n{'=' * 70}\n")
        log_fh.flush()
        real_stdout, real_stderr = sys.stdout, sys.stderr
        sys.stdout = _Tee(real_stdout, log_fh)
        sys.stderr = _Tee(real_stderr, log_fh)
        try:
            fn(*args, **kwargs)
        except Exception as e:
            print(f"\n[ERROR] {type(e).__name__}: {e}")
            raise
        finally:
            sys.stdout, sys.stderr = real_stdout, real_stderr


def read_recent_log(max_chars: int = 20000) -> str:
    """Returns the tail of the log file (most recent output), for display
    on the dashboard's Logs page."""
    if not LOG_FILE.exists():
        return "No log file yet — run something from the dashboard or main.py first."
    text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text
