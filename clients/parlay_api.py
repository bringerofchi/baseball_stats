"""
ParlayAPI client (https://parlay-api.com) — a second odds data source,
added alongside The Odds API rather than replacing it.

What makes this worth having its own integration rather than just being
"another odds key": ParlayAPI documents a dedicated historical
closing-odds endpoint (/v1/historical/sports/{sport_key}/closing-odds)
that returns the true closing line for a past event directly, given just
a date. If this works as documented, it's a meaningfully better foundation
for CLV than our current approach in pipeline/ingest.py, which
approximates a closing line by polling repeatedly throughout the day and
guarding against writing over it once a game starts (see
_has_game_started() in pipeline/ingest.py). A direct "give me the actual
closing line for this date" call is simpler and more reliable than
"poll enough times and hope you caught the right moment."

Confirmed from ParlayAPI's public docs/cookbook before writing this:
  - Base URL: https://parlay-api.com
  - Auth: header 'X-API-Key: <key>' (not a query param, unlike The Odds API)
  - Credit-based billing (like The Odds API): 401 = bad key, 403 = quota
    exceeded for the month
  - sport_key convention appears to match The Odds API's ("baseball_mlb")
  - markets param uses the same short codes ("h2h", etc.)
  - Advertised as "drop-in for the-odds-api" — suggesting (not confirmed)
    the /odds response shape closely mirrors The Odds API's

NOT confirmed (no full example response body found in public docs): the
exact JSON structure of either endpoint's response. Both methods below
try the shape suggested by the "drop-in for the-odds-api" positioning
first, and print a diagnostic with the raw response structure if that
guess doesn't parse — same pattern used successfully for every other
integration in this project. Expect one round-trip against a real request
to confirm or correct the exact field names.
"""
import requests

import config


class ParlayAPIClient:
    BASE_URL = "https://parlay-api.com"

    def __init__(self, api_key: str = None, mock_mode: bool = None):
        self.api_key = api_key or config.PARLAY_API_KEY
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode

    def _get(self, path: str, params: dict = None):
        if self.mock_mode:
            return None  # mock handled per-method below, not centrally

        if not self.api_key:
            raise RuntimeError(
                "PARLAY_API_KEY is not set. Add it via the dashboard's Settings "
                "page, or set MLB_EDGE_MOCK_MODE=true to develop without it."
            )

        url = f"{self.BASE_URL}{path}"
        headers = {"X-API-Key": self.api_key}
        resp = requests.get(url, params=params or {}, headers=headers,
                             timeout=config.REQUEST_TIMEOUT_SECONDS)

        if resp.status_code == 401:
            print("[parlayapi] WARNING: 401 Unauthorized — check PARLAY_API_KEY is correct.")
            return None
        if resp.status_code == 403:
            print("[parlayapi] WARNING: 403 — likely out of monthly credits. "
                  "Check https://parlay-api.com/dashboard for credits remaining.")
            return None
        if resp.status_code != 200:
            print(f"[parlayapi] WARNING: {resp.status_code} on {path}.")
            return None

        return resp.json()

    # -- Public methods ----------------------------------------------------

    def get_current_odds(self, sport_key: str = "baseball_mlb", markets: str = "h2h", regions: str = "us"):
        """
        Live/upcoming odds snapshot. Mirrors OddsAPIClient.get_current_odds()
        in shape for easy interchange — confirmed against a real response:
        bare JSON list, home_team/away_team, bookmakers[].markets[].outcomes[].

        oddsFormat=american is explicit and required: a real test call
        without it returned decimal odds (1.847, 2.06, etc.), which every
        American-odds calculation in this project (american_to_implied_prob,
        CLV, profit) would silently misinterpret as if they were American
        odds. Confirmed The Odds API's oddsFormat param name works the same
        way here, consistent with ParlayAPI's "drop-in for the-odds-api"
        positioning.
        """
        if self.mock_mode:
            return self._mock_current_odds()

        data = self._get(f"/v1/sports/{sport_key}/odds",
                          params={"markets": markets, "regions": regions, "oddsFormat": "american"})
        if data is None:
            return []

        events = self._extract_event_list(data)
        if events is None:
            print(f"[parlayapi] WARNING: /odds response didn't match the expected shape. "
                  f"Top-level keys/type: {self._describe(data)}. Update "
                  f"ParlayAPIClient.get_current_odds() in clients/parlay_api.py once the "
                  f"real shape is known.")
            return []
        return events

    def get_closing_odds(self, date_str: str, sport_key: str = "baseball_mlb", markets: str = "h2h", regions: str = "us"):
        """
        The dedicated historical closing-odds endpoint — the actual reason
        this client exists.

        CONFIRMED shape from a real response (2026-07-18): NOT the nested
        bookmakers/markets/outcomes shape get_current_odds() uses. Instead
        a flat list, one row per (game, bookmaker) pair:
            {'game_date', 'sport_key', 'home_team', 'away_team',
             'commence_time' (observed always None here), 'bookmaker',
             'bookmaker_title', 'season', 'result', 'home_score',
             'away_score', 'home_odds', 'draw_odds', 'away_odds',
             'market_keys', 'market_key'}
        Bookmaker keys come in pairs: 'fanduel' and 'fanduel_open',
        'pinnacle' and 'pinnacle_open', etc. — the '_open' suffix appears
        to mark that book's OPENING line, with the unsuffixed key being
        the CLOSING line. That means a single call here can yield both
        opening and closing odds per bookmaker for a historical date,
        which is a real simplification opportunity over the polling
        approach pipeline/ingest.py currently uses — see
        group_closing_odds_by_game() below for a usable parsed form.

        Also observed: 'result'/'home_score'/'away_score' were empty/None
        even for a clearly-past date — this endpoint is odds-only, not a
        results source. Outcomes still need to come from MLB Stats API
        (pipeline/evaluate.py::auto_store_outcomes), unchanged.

        Also observed: team name formatting isn't fully consistent even
        within ParlayAPI's own data (e.g. 'LA Angels' from one bookmaker
        vs 'Los Angeles Angels' from others for the same game) —
        pipeline/ingest.py's existing nickname-based fallback matching
        already handles this correctly (last-word match), so no separate
        fix needed there.
        """
        if self.mock_mode:
            return self._mock_closing_odds()

        data = self._get(f"/v1/historical/sports/{sport_key}/closing-odds",
                          params={"date": date_str, "markets": markets, "regions": regions,
                                  "oddsFormat": "american"})
        if data is None:
            return []

        events = self._extract_event_list(data)
        if events is None:
            print(f"[parlayapi] WARNING: /closing-odds response didn't match the expected "
                  f"shape. Top-level keys/type: {self._describe(data)}. Update "
                  f"ParlayAPIClient.get_closing_odds() in clients/parlay_api.py once the "
                  f"real shape is known.")
            return []
        return events

    @staticmethod
    def group_closing_odds_by_game(rows: list) -> dict:
        """
        Parses the flat per-bookmaker rows from get_closing_odds() into a
        more usable structure:
            {(home_team, away_team): {
                bookmaker_base_name: {
                    'opening': {'home_odds': ..., 'away_odds': ...} or None,
                    'closing': {'home_odds': ..., 'away_odds': ...} or None,
                }
            }}
        Pairs each 'X' / 'X_open' bookmaker key under the same base name
        'X', splitting into 'opening' vs 'closing' buckets. A bookmaker
        with only one of the two (no matching pair found) still gets an
        entry, just with the other side as None — better to surface a
        partial pair than silently drop it.
        """
        grouped = {}
        for row in rows:
            game_key = (row.get("home_team"), row.get("away_team"))
            bookmaker = row.get("bookmaker", "")
            is_opening = bookmaker.endswith("_open")
            base_name = bookmaker[:-5] if is_opening else bookmaker  # strip '_open'

            game_bucket = grouped.setdefault(game_key, {})
            book_bucket = game_bucket.setdefault(base_name, {"opening": None, "closing": None})
            side = "opening" if is_opening else "closing"
            book_bucket[side] = {
                "home_odds": row.get("home_odds"),
                "away_odds": row.get("away_odds"),
            }
        return grouped

    # -- Defensive parsing helpers -----------------------------------------

    @staticmethod
    def _extract_event_list(data):
        """
        Tries the shape The Odds API uses (a bare JSON list of event
        objects, each with home_team/away_team/bookmakers) first, since
        ParlayAPI advertises itself as a drop-in replacement. Falls back to
        a couple of plausible wrapped-list shapes. Returns None (not []) if
        nothing recognizable is found, so the caller can tell "genuinely no
        events" apart from "shape didn't match."
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("events", "data", "results", "odds"):
                if isinstance(data.get(key), list):
                    return data[key]
        return None

    @staticmethod
    def _describe(data):
        if isinstance(data, dict):
            return f"dict with keys {list(data.keys())}"
        if isinstance(data, list):
            return f"list of {len(data)} items, first item: {data[0] if data else 'empty'}"
        return f"{type(data).__name__}: {data}"

    # -- Mock data -----------------------------------------------------------

    def _mock_current_odds(self):
        """Confirmed real shape (2026-07-18 test): nested bookmakers/markets/outcomes."""
        return [
            {
                "id": "mock_parlay_evt_1",
                "sport_key": "baseball_mlb",
                "commence_time": "2026-07-06T23:05:00Z",
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "bookmakers": [
                    {"key": "draftkings", "title": "DraftKings", "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "New York Yankees", "price": -148},
                            {"name": "Boston Red Sox", "price": 128},
                        ]},
                    ]},
                ],
                "probable_pitchers": {
                    "home": {"name": "Gerrit Cole", "id": 543037},
                    "away": {"name": "Brayan Bello", "id": 678394},
                    "venue": "Yankee Stadium", "source": "mlb_stats_api",
                },
            },
        ]

    def _mock_closing_odds(self):
        """
        Confirmed real shape (2026-07-18 test): FLAT, one row per
        (game, bookmaker) — not nested like get_current_odds(). Bookmaker
        keys come in 'X' / 'X_open' pairs (closing / opening).
        """
        return [
            {
                "game_date": "2026-07-06", "sport_key": "baseball_mlb",
                "home_team": "New York Yankees", "away_team": "Boston Red Sox",
                "commence_time": None, "bookmaker": "draftkings", "bookmaker_title": "DraftKings",
                "season": "2026", "result": "", "home_score": None, "away_score": None,
                "home_odds": -142, "draw_odds": None, "away_odds": 122,
                "market_keys": ["h2h"], "market_key": "h2h",
            },
            {
                "game_date": "2026-07-06", "sport_key": "baseball_mlb",
                "home_team": "New York Yankees", "away_team": "Boston Red Sox",
                "commence_time": None, "bookmaker": "draftkings_open", "bookmaker_title": "Draftkings_Open",
                "season": "2026", "result": "", "home_score": None, "away_score": None,
                "home_odds": -150, "draw_odds": None, "away_odds": 130,
                "market_keys": ["h2h"], "market_key": "h2h",
            },
        ]
