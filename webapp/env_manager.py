"""
Reads and writes the project's .env file for the dashboard's Settings
page, so API keys can be entered through a web form instead of editing
the file by hand in a text editor.

Always rewrites the full file in a fixed, known format rather than trying
to preserve arbitrary existing formatting/comments — simpler and less
fragile than a line-by-line patch, and the file only ever holds the fixed
set of keys this project uses.
"""
from pathlib import Path

import config

ENV_TEMPLATE = """# Generated/updated by the MLB Edge Lab dashboard Settings page.
# You can also edit this file directly if you prefer.

SPORTSDATAIO_API_KEY={SPORTSDATAIO_API_KEY}
ODDS_API_KEY={ODDS_API_KEY}
OPTICODDS_API_KEY={OPTICODDS_API_KEY}
WEATHER_API_KEY={WEATHER_API_KEY}
PARLAY_API_KEY={PARLAY_API_KEY}
SHARPAPI_KEY={SHARPAPI_KEY}

MLB_EDGE_MOCK_MODE={MLB_EDGE_MOCK_MODE}

ODDS_API_REGIONS={ODDS_API_REGIONS}
ODDS_API_BOOKMAKERS={ODDS_API_BOOKMAKERS}

# Live odds source: auto (Odds API, fall back to ParlayAPI on failure),
# odds_api (Odds API only), parlay_api (ParlayAPI only)
ODDS_SOURCE={ODDS_SOURCE}
"""


def get_current_values() -> dict:
    """Current values as currently loaded in config (reflects .env if
    present, or blank defaults if not)."""
    return {
        "SPORTSDATAIO_API_KEY": config.SPORTSDATAIO_API_KEY,
        "ODDS_API_KEY": config.ODDS_API_KEY,
        "OPTICODDS_API_KEY": config.OPTICODDS_API_KEY,
        "WEATHER_API_KEY": config.WEATHER_API_KEY,
        "PARLAY_API_KEY": config.PARLAY_API_KEY,
        "SHARPAPI_KEY": config.SHARPAPI_KEY,
        "MLB_EDGE_MOCK_MODE": "true" if config.MOCK_MODE else "false",
        "ODDS_API_REGIONS": config.REGIONS,
        "ODDS_API_BOOKMAKERS": config.BOOKMAKERS_FILTER,
        "ODDS_SOURCE": config.ODDS_SOURCE,
    }


def save_values(values: dict):
    """Writes a fresh .env file from the given values dict (missing keys
    default to empty string / mock-mode-true) and reloads config so the
    running dashboard picks up the change immediately."""
    merged = {
        "SPORTSDATAIO_API_KEY": values.get("SPORTSDATAIO_API_KEY", "").strip(),
        "ODDS_API_KEY": values.get("ODDS_API_KEY", "").strip(),
        "OPTICODDS_API_KEY": values.get("OPTICODDS_API_KEY", "").strip(),
        "WEATHER_API_KEY": values.get("WEATHER_API_KEY", "").strip(),
        "PARLAY_API_KEY": values.get("PARLAY_API_KEY", "").strip(),
        "SHARPAPI_KEY": values.get("SHARPAPI_KEY", "").strip(),
        "MLB_EDGE_MOCK_MODE": "true" if values.get("MLB_EDGE_MOCK_MODE") == "true" else "false",
        "ODDS_API_REGIONS": values.get("ODDS_API_REGIONS", "us").strip() or "us",
        "ODDS_API_BOOKMAKERS": values.get("ODDS_API_BOOKMAKERS", "").strip(),
        "ODDS_SOURCE": (values.get("ODDS_SOURCE", "auto").strip().lower()
                        if values.get("ODDS_SOURCE", "auto").strip().lower()
                        in ("auto", "odds_api", "parlay_api", "sharpapi") else "auto"),
    }
    content = ENV_TEMPLATE.format(**merged)
    config.ENV_PATH.write_text(content)
    config.reload()
    return merged
