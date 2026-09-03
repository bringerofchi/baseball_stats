"""
SportsDataIO MLB API client.

Docs: https://sportsdata.io/developers/api-documentation/mlb

Endpoints used (typical SportsDataIO MLB v3 paths — verify against your
subscription tier/docs, as exact paths vary by plan):
  - GamesByDate/{date}                -> schedule + results for a date
  - PlayerGameStatsByDate/{date}       -> per-player box score stats (for ERA etc.)
  - Injuries                          -> current injury list
  - Standings/{season}                -> team standings

All methods return plain Python dicts/lists (already-parsed JSON).
When config.MOCK_MODE is True, returns synthetic sample data instead of
calling the network, so the pipeline can be built/tested without a live key.
"""
import requests

import config


class SportsDataIOClient:
    def __init__(self, api_key: str = None, mock_mode: bool = None):
        self.api_key = api_key or config.SPORTSDATAIO_API_KEY
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self.base_url = config.SPORTSDATAIO_BASE_URL

    def _get(self, path: str, params: dict = None, required: bool = True):
        if self.mock_mode:
            return self._mock_response(path)

        if not self.api_key:
            raise RuntimeError(
                "SPORTSDATAIO_API_KEY is not set. Add it to your .env file, "
                "or set MLB_EDGE_MOCK_MODE=true to develop against mock data."
            )

        url = f"{self.base_url}/{path}"
        params = params or {}
        params["key"] = self.api_key
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)

        if resp.status_code in (401, 403, 404) and not required:
            # Endpoint likely unavailable on this subscription tier. Degrade
            # gracefully rather than crashing the whole ingestion run — a
            # missing starters/injuries feed shouldn't block games/odds from
            # being stored.
            print(f"[sportsdataio] WARNING: {resp.status_code} on {path} — "
                  f"this endpoint may not be included in your plan tier. "
                  f"Skipping; other data will still be ingested.")
            return []

        resp.raise_for_status()
        return resp.json()

    # -- Public methods ----------------------------------------------------

    def get_games_by_date(self, date_str: str):
        """date_str: 'YYYY-MM-DD'. Returns list of game dicts."""
        return self._get(f"scores/json/GamesByDate/{date_str}")  # required=True: no games = nothing to do

    def get_starting_pitchers(self, date_str: str):
        """
        SportsDataIO doesn't always expose a dedicated 'starting pitchers'
        endpoint on lower tiers; often derived from GamesByDate (probable
        pitcher fields) or ProjectedStarters. Not required=True — if your
        plan doesn't include this endpoint, ingestion continues without
        starter data rather than crashing, and prints a warning telling you
        which endpoint to check against your actual SportsDataIO plan docs.
        """
        return self._get(f"scores/json/ProjectedStarters/{date_str}", required=False)

    def get_player_season_stats(self, season: str):
        """season: e.g. '2026'. Returns list of player season stat dicts (incl. ERA)."""
        return self._get(f"scores/json/PlayerSeasonStats/{season}", required=False)

    def get_injuries(self):
        return self._get("scores/json/Injuries", required=False)

    def get_standings(self, season: str):
        return self._get(f"scores/json/Standings/{season}")

    # -- Mock data -----------------------------------------------------------

    def _mock_response(self, path: str):
        if "GamesByDate" in path:
            return [
                {
                    "GameID": 10001,
                    "Day": "2026-07-06",
                    "HomeTeam": "NYY",
                    "AwayTeam": "BOS",
                    "Stadium": "Yankee Stadium",
                    "Status": "Scheduled",
                    "HomeTeamStartingPitcher": "Gerrit Cole",
                    "AwayTeamStartingPitcher": "Brayan Bello",
                    "HomeTeamStartingPitcherID": 20001,
                    "AwayTeamStartingPitcherID": 20002,
                    "HomeDaysRest": 4,
                    "AwayDaysRest": 5,
                    "HomePitchCountLastStart": 92,
                    "AwayPitchCountLastStart": 88,
                },
                {
                    "GameID": 10002,
                    "Day": "2026-07-06",
                    "HomeTeam": "LAD",
                    "AwayTeam": "SF",
                    "Stadium": "Dodger Stadium",
                    "Status": "Scheduled",
                    "HomeTeamStartingPitcher": "Yoshinobu Yamamoto",
                    "AwayTeamStartingPitcher": "Logan Webb",
                    "HomeTeamStartingPitcherID": 20003,
                    "AwayTeamStartingPitcherID": 20004,
                    "HomeDaysRest": 5,
                    "AwayDaysRest": 4,
                    "HomePitchCountLastStart": 95,
                    "AwayPitchCountLastStart": 101,
                },
            ]
        if "ProjectedStarters" in path:
            # Kept for backward compatibility / plans that do serve this
            # endpoint; ingest_starters() no longer depends on it (see
            # pipeline/ingest.py), since starter fields are now read
            # directly off GamesByDate per SportsDataIO's own docs.
            return []
        if "PlayerSeasonStats" in path:
            # Keyed by PlayerID to match HomeTeamStartingPitcherID /
            # AwayTeamStartingPitcherID above, per _build_era_lookup().
            return [
                {"PlayerID": 20001, "ERA": 3.10},
                {"PlayerID": 20002, "ERA": 4.25},
                {"PlayerID": 20003, "ERA": 2.85},
                {"PlayerID": 20004, "ERA": 3.02},
            ]
        if "Injuries" in path:
            return []
        if "Standings" in path:
            return []
        return {}
