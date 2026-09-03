"""
The Odds API client (https://the-odds-api.com/).

Pulls moneyline, run line (spreads), and totals across sportsbooks.
The Odds API's free/standard tier gives you a live snapshot of current
odds; to get true "opening" vs "closing" lines you need either:
  (a) the paid Historical Odds endpoint, or
  (b) to snapshot odds yourself at two points in time (e.g. once when
      games are first posted, once ~5 min before first pitch) and store
      both snapshots.

This client supports both patterns:
  - get_current_odds(): live snapshot -> use it twice daily via your own
    scheduler and label the earlier one "opening" and the later "closing"
    in the ingestion layer.
  - get_historical_odds(): if you have historical-odds API access.
"""
import requests

import config


class OddsAPIClient:
    def __init__(self, api_key: str = None, mock_mode: bool = None):
        self.api_key = api_key or config.ODDS_API_KEY
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode
        self.base_url = config.ODDS_API_BASE_URL
        self.sport_key = config.ODDS_API_SPORT_KEY

    def _get(self, path: str, params: dict = None):
        if self.mock_mode:
            return self._mock_response(path)

        if not self.api_key:
            raise RuntimeError(
                "ODDS_API_KEY is not set. Add it to your .env file, "
                "or set MLB_EDGE_MOCK_MODE=true to develop against mock data."
            )

        url = f"{self.base_url}/{path}"
        params = params or {}
        params["apiKey"] = self.api_key
        resp = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()

    # -- Public methods ------------------------------------------------------

    def get_current_odds(self, markets: str = "h2h"):
        """
        Live odds snapshot for all upcoming MLB games.

        Defaults to moneyline ('h2h') only, not 'h2h,spreads,totals'. The
        Odds API's free tier is credit-based, not request-based: each call
        costs (number of markets) x (number of regions) credits out of a
        500/month budget. None of the three edge signals built so far
        (sp_mismatch, bullpen_fatigue, overreaction) use spreads or totals
        at all — only moneyline — so requesting all three was burning 3x
        the credits for data that was stored but never read. Pass an
        explicit markets string (e.g. "h2h,totals") if a future edge needs
        totals data; just know it changes the credit cost per call.
        """
        return self._get(
            f"sports/{self.sport_key}/odds",
            params={
                "regions": config.REGIONS,
                "markets": markets,
                "oddsFormat": "american",
                "bookmakers": config.BOOKMAKERS_FILTER or None,
            },
        )

    def get_historical_odds(self, date_iso: str, markets: str = "h2h,spreads,totals"):
        """
        Requires The Odds API historical-odds add-on.
        date_iso: full ISO-8601 timestamp, e.g. '2026-07-06T17:00:00Z'
        """
        return self._get(
            f"historical/sports/{self.sport_key}/odds",
            params={
                "regions": config.REGIONS,
                "markets": markets,
                "oddsFormat": "american",
                "date": date_iso,
            },
        )

    # -- Mock data -------------------------------------------------------------

    def _mock_response(self, path: str):
        return [
            {
                "id": "mock_evt_10001",
                "commence_time": "2026-07-06T23:05:00Z",
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "New York Yankees", "price": -145},
                                    {"name": "Boston Red Sox", "price": 125},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "point": 8.5, "price": -110},
                                    {"name": "Under", "point": 8.5, "price": -110},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "New York Yankees", "point": -1.5, "price": 145},
                                    {"name": "Boston Red Sox", "point": 1.5, "price": -165},
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "id": "mock_evt_10002",
                "commence_time": "2026-07-07T02:10:00Z",
                "home_team": "Los Angeles Dodgers",
                "away_team": "San Francisco Giants",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Los Angeles Dodgers", "price": -175},
                                    {"name": "San Francisco Giants", "price": 150},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "point": 8.0, "price": -105},
                                    {"name": "Under", "point": 8.0, "price": -115},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Los Angeles Dodgers", "point": -1.5, "price": 105},
                                    {"name": "San Francisco Giants", "point": 1.5, "price": -125},
                                ],
                            },
                        ],
                    }
                ],
            },
        ]
