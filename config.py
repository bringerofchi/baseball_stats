"""
Config loader for MLB Edge Lab.

All secrets are read from environment variables — never hardcode API keys.
Copy .env.example to .env and fill in your keys, use the dashboard's
Settings page (writes .env for you), or export them in your shell.

Values are (re)loaded by _load(), which populates this module's globals.
reload() re-runs it after .env changes on disk (e.g. saved via the
dashboard's Settings page) so the running server picks up new keys
immediately — no restart needed.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def _load():
    global SPORTSDATAIO_API_KEY, ODDS_API_KEY, OPTICODDS_API_KEY, WEATHER_API_KEY, PARLAY_API_KEY, SHARPAPI_KEY
    global MOCK_MODE, DB_PATH, REGIONS, BOOKMAKERS_FILTER, ODDS_SOURCE

    # Re-import dotenv's loader fresh each time and force override=True, so
    # values already in os.environ from a previous load() don't shadow an
    # updated .env on disk.
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=ENV_PATH, override=True)
    except ImportError:
        pass

    SPORTSDATAIO_API_KEY = os.environ.get("SPORTSDATAIO_API_KEY", "")
    ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
    OPTICODDS_API_KEY = os.environ.get("OPTICODDS_API_KEY", "")
    WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")
    PARLAY_API_KEY = os.environ.get("PARLAY_API_KEY", "")
    # SharpAPI: client built in clients/sharpapi.py (2026-07-27), confirmed
    # against docs.sharpapi.io's real API reference. Usable as a third
    # live-odds fallback — see ODDS_SOURCE below.
    SHARPAPI_KEY = os.environ.get("SHARPAPI_KEY", "")

    MOCK_MODE = os.environ.get("MLB_EDGE_MOCK_MODE", "true").lower() in ("1", "true", "yes")

    # Mock mode and live mode ALWAYS use separate database files by default.
    # This is a deliberate structural safeguard, not just a naming
    # convention: without it, toggling MLB_EDGE_MOCK_MODE on and off (e.g.
    # while testing) writes synthetic sample games into the same file as
    # real games, and matching logic (keyed off date + team code) can
    # silently confuse a leftover mock game for a real one — which is
    # exactly what happened during initial setup here. If you explicitly
    # set MLB_EDGE_DB_PATH, that override is respected as-is (no mock/live
    # split) — you're taking responsibility for keeping them separate.
    _explicit_db_path = os.environ.get("MLB_EDGE_DB_PATH")
    if _explicit_db_path:
        DB_PATH = _explicit_db_path
    elif MOCK_MODE:
        DB_PATH = str(BASE_DIR / "mlb_edge_lab_mock.db")
    else:
        DB_PATH = str(BASE_DIR / "mlb_edge_lab.db")

    REGIONS = os.environ.get("ODDS_API_REGIONS", "us")
    BOOKMAKERS_FILTER = os.environ.get("ODDS_API_BOOKMAKERS", "")

    # Which live-odds source to use in pipeline.ingest.ingest_odds():
    #   "auto"       (default) - try The Odds API, then ParlayAPI, then
    #                 SharpAPI, automatically falling back on failure
    #   "odds_api"   - The Odds API only, no fallback (old behavior)
    #   "parlay_api" - ParlayAPI only
    #   "sharpapi"   - SharpAPI only
    ODDS_SOURCE = os.environ.get("ODDS_SOURCE", "auto").strip().lower()


def reload():
    """Call after writing a new .env (e.g. from the dashboard's Settings
    page) so the running process picks up new keys without a restart."""
    _load()


_load()

# --- API base URLs (static, not env-dependent) -----------------------------
SPORTSDATAIO_BASE_URL = "https://api.sportsdata.io/v3/mlb"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
ODDS_API_SPORT_KEY = "baseball_mlb"

REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_STAKE_UNITS = 1.0

