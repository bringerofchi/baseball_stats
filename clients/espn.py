"""
ESPN client — used specifically as a real, unscrambled source of pitcher
ERA, since SportsDataIO's free trial tier scrambles stats/scores/odds by
5-20% (schedules/teams/players are NOT scrambled, which is why game
matching has been working fine while ERA has not). See SportsDataIO's own
"Scrambled Data" support article for the exact policy.

ESPN doesn't publish an official API, but its website/app are backed by
public, unauthenticated JSON endpoints that are widely used for exactly
this purpose (community-documented, e.g. github.com/pseudo-r/Public-ESPN-API).
No API key needed. These are unofficial and could change without notice —
treat this client the same defensive way as the SportsDataIO integration:
try the documented shape, and if the response doesn't match, print
diagnostics instead of failing silently, so a mismatch is a quick fix
rather than another guessing round.

This client is intentionally decoupled from SportsDataIO — it matches
pitchers by normalized full name (not a shared player ID, since the two
providers don't share an ID system), which is why _normalize_name() exists.
"""
import requests

import config
from clients.name_utils import normalize_name


class ESPNClient:
    STATS_BASE = "https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb"

    def __init__(self, mock_mode: bool = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode

    def get_pitching_era_lookup(self, season: str) -> dict:
        """
        Returns {normalized_pitcher_name: era} covering all MLB pitchers
        with a qualifying stat line for the season, by paging through
        ESPN's pitching statistics leaderboard.
        """
        if self.mock_mode:
            return self._mock_era_lookup()

        lookup = {}
        offset = 0
        limit = 50
        diagnostic_shown = False
        max_pages = 30  # safety cap: ~1500 pitchers, far more than a season needs

        for _ in range(max_pages):
            params = {
                "category": "pitching",
                "season": season,
                "seasontype": 2,  # regular season
                "limit": limit,
                "offset": offset,
            }
            try:
                resp = requests.get(f"{self.STATS_BASE}/statistics/byathlete",
                                     params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
            except requests.RequestException as e:
                print(f"[espn] WARNING: request failed ({type(e).__name__}: {e}) fetching pitching "
                      f"stats at offset={offset}. Stopping ERA lookup; games/odds ingestion is "
                      f"unaffected, but starter ERA will be incomplete for this run.")
                break

            if resp.status_code != 200:
                print(f"[espn] WARNING: {resp.status_code} fetching pitching stats "
                      f"(offset={offset}). Stopping pagination; partial ERA data may result.")
                break

            data = resp.json()
            athletes = data.get("athletes") or data.get("items") or []
            if not athletes:
                if offset == 0:
                    print(f"[espn] WARNING: pitching-stats request succeeded (HTTP 200) but returned "
                          f"zero athletes on the first page — the response shape likely doesn't match "
                          f"'athletes'/'items' as expected. Top-level response keys: {list(data.keys())}. "
                          f"Update ESPNClient.get_pitching_era_lookup() in clients/espn.py with the "
                          f"correct key.")
                break

            for entry in athletes:
                name, era = self._extract_name_and_era(entry)
                if name is None:
                    if not diagnostic_shown:
                        print(f"[espn] Couldn't find a recognizable name/ERA shape in a "
                              f"pitching-stats entry. Raw entry keys: {list(entry.keys())}. "
                              f"Full first entry for reference: {entry}")
                        diagnostic_shown = True
                    continue
                if era is not None:
                    lookup[normalize_name(name)] = era

            offset += limit
            if len(athletes) < limit:
                break  # last page

        return lookup

    def _extract_name_and_era(self, entry: dict):
        """
        ESPN's statistics/byathlete shape isn't fully pinned down without a
        live response to check, so this tries a few plausible paths in
        order. If none work, the caller prints a diagnostic with the raw
        entry so the real shape can be added here in one pass.
        """
        # Candidate path 1: {"athlete": {"displayName": ...}, "stats": [...]}
        # with a parallel "categories"/"names" list elsewhere giving stat
        # order — too fragile to guess the index, so this path only used
        # if a labeled dict is available instead of a positional list.
        athlete = entry.get("athlete", {})
        name = athlete.get("displayName") or athlete.get("fullName") or entry.get("displayName")

        stats = entry.get("stats")
        era = None
        if isinstance(stats, dict):
            for key in ("ERA", "era", "earnedRunAverage"):
                if key in stats:
                    era = self._to_float(stats[key])
                    break
        elif isinstance(stats, list):
            # Positional list of {"name": "ERA", "value": 3.21}-style dicts
            for s in stats:
                if isinstance(s, dict) and s.get("name", "").upper() in ("ERA", "EARNEDRUNAVERAGE"):
                    era = self._to_float(s.get("value") or s.get("displayValue"))
                    break

        return name, era

    @staticmethod
    def _to_float(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _mock_era_lookup(self):
        return {
            normalize_name("Gerrit Cole"): 3.10,
            normalize_name("Brayan Bello"): 4.25,
            normalize_name("Yoshinobu Yamamoto"): 2.85,
            normalize_name("Logan Webb"): 3.02,
        }
