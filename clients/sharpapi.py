"""
SharpAPI client (https://api.sharpapi.io/api/v1) — a third live-odds
source, usable as another fallback alongside ParlayAPI.

Previously blocked: only SharpAPI's marketing site (sharpapi.io) could be
found, with no independently verifiable API docs. That's no longer true —
docs.sharpapi.io is a real, separate documentation site with a full
OpenAPI 3.1 spec, confirmed endpoints, auth methods, and response shapes.
Confirmed directly from there before writing this (2026-07-27):

  - Base URL: https://api.sharpapi.io/api/v1
  - Auth: header 'X-API-Key: <key>' (also supports Authorization: Bearer
    and an api_key query param, but the header is what every other client
    in this project already uses, so kept consistent)
  - GET /odds returns a FLAT list, one row per (event, sportsbook, market,
    selection) — NOT nested like The Odds API. Relevant fields per row:
    sportsbook, home_team, away_team, market_type, selection,
    selection_type ("home"/"away"), odds_american, event_start_time,
    is_live.
  - market_type "moneyline" is the equivalent of The Odds API's "h2h" —
    mapped below so downstream code (pipeline/ingest.py) doesn't need to
    know the difference.
  - Free tier only returns DraftKings + FanDuel; higher tiers add more
    books. Not selectable here — whatever the key's tier allows is what
    comes back.
  - Pagination: cursor-based (`next_cursor`) is recommended for multi-page
    scans; `limit` maxes out at 200. A single day's MLB slate fits
    comfortably in one page even on higher tiers, but pagination is
    still implemented (capped) in case a busy day with many books doesn't.
  - Error envelope: {"error": {"code": ..., "message": ...}}. Auth
    failures are 401 (missing_api_key / invalid_api_key / expired_api_key
    / disabled_api_key), quota/tier issues are 403 (tier_restricted),
    rate limits are 429 (rate_limited).
"""
import requests

import config


class SharpAPIClient:
    BASE_URL = "https://api.sharpapi.io/api/v1"
    MAX_PAGES = 5  # safety cap on cursor-following, well above what one day's MLB slate needs

    def __init__(self, api_key: str = None, mock_mode: bool = None):
        self.api_key = api_key or config.SHARPAPI_KEY
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode

    def _get(self, path: str, params: dict = None):
        if self.mock_mode:
            return None  # mock handled per-method below, not centrally

        if not self.api_key:
            raise RuntimeError(
                "SHARPAPI_KEY is not set. Add it via the dashboard's Settings "
                "page, or set MLB_EDGE_MOCK_MODE=true to develop without it."
            )

        url = f"{self.BASE_URL}{path}"
        headers = {"X-API-Key": self.api_key}
        resp = requests.get(url, params=params or {}, headers=headers,
                             timeout=config.REQUEST_TIMEOUT_SECONDS)

        if resp.status_code in (401, 403, 429):
            try:
                err = resp.json().get("error", {})
                code, msg = err.get("code", "?"), err.get("message", "")
            except ValueError:
                code, msg = "?", ""
            print(f"[sharpapi] WARNING: {resp.status_code} {code} — {msg}")
            return None
        if resp.status_code != 200:
            print(f"[sharpapi] WARNING: {resp.status_code} on {path}.")
            return None

        return resp.json()

    # -- Public methods ----------------------------------------------------

    def get_current_odds(self, league: str = "mlb", market: str = "moneyline"):
        """
        Live/upcoming odds snapshot, reshaped into the same nested
        bookmakers[].markets[].outcomes[] shape OddsAPIClient and
        ParlayAPIClient use, so pipeline/ingest.py can treat all three
        sources interchangeably.
        """
        if self.mock_mode:
            return self._mock_current_odds()

        rows = []
        cursor = None
        for _ in range(self.MAX_PAGES):
            params = {"league": league, "market": market, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/odds", params=params)
            if data is None:
                break
            rows.extend(data.get("data", []))
            pagination = data.get("pagination", {})
            if pagination.get("has_more") and pagination.get("next_cursor"):
                cursor = pagination["next_cursor"]
            else:
                break

        return self._group_rows_into_events(rows)

    @staticmethod
    def _group_rows_into_events(rows: list) -> list:
        """
        Groups SharpAPI's flat per-(event, sportsbook, market, selection)
        rows into the nested event shape used elsewhere in this project:
            [{home_team, away_team, commence_time,
              bookmakers: [{key, markets: [{key, outcomes: [{name, price}]}]}]}]
        """
        events = {}
        for row in rows:
            home, away = row.get("home_team"), row.get("away_team")
            if not home or not away:
                continue
            event_key = (home, away)
            event = events.setdefault(event_key, {
                "home_team": home,
                "away_team": away,
                "commence_time": row.get("event_start_time"),
                "bookmakers": {},
            })

            book_key = row.get("sportsbook", "unknown")
            book = event["bookmakers"].setdefault(book_key, {"key": book_key, "markets": {}})

            # "moneyline" -> "h2h" to match The Odds API's market key, which
            # pipeline/ingest.py already knows how to parse.
            market_type = row.get("market_type")
            market_key = "h2h" if market_type == "moneyline" else market_type
            market = book["markets"].setdefault(market_key, {"key": market_key, "outcomes": []})

            market["outcomes"].append({
                "name": row.get("selection"),
                "price": row.get("odds_american"),
            })

        # Convert the nested dicts (used above for easy grouping) into lists.
        out = []
        for event in events.values():
            event["bookmakers"] = [
                {"key": b["key"], "markets": list(b["markets"].values())}
                for b in event["bookmakers"].values()
            ]
            out.append(event)
        return out

    # -- Mock data -----------------------------------------------------------

    def _mock_current_odds(self):
        return [
            {
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "commence_time": "2026-07-06T23:05:00Z",
                "bookmakers": [
                    {"key": "draftkings", "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "New York Yankees", "price": -140},
                            {"name": "Boston Red Sox", "price": 120},
                        ]},
                    ]},
                ],
            },
        ]
