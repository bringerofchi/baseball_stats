"""
MLB Stats API client — the official MLB data source, used here for game
schedule, probable starting pitchers, and pitching ERA.

This is unofficial in the sense that MLB doesn't publish formal API docs
for public use, but the endpoints are widely used and well-documented by
the open-source community (e.g. github.com/toddrob99/MLB-StatsAPI,
github.com/pseudo-r/Public-MLB-API). No API key required.

Why this replaced SportsDataIO for games/starters and ESPN for ERA:
- SportsDataIO's free trial scrambles stats/scores/odds by 5-20% from the
  real value (confirmed via their own "Scrambled Data" support article),
  which would have quietly poisoned the SP-mismatch signal.
- This is the authoritative source (MLB's own data), not scrambled, and
  not gated behind a paid tier for the basics used here.
- The schedule endpoint includes probable pitchers directly via a hydrate
  parameter, avoiding a second lookup call.
- The stats endpoint (bdfed.stitch.mlbinfra.com, MLB's own stats backend)
  returns real season ERA in a single call, no pagination needed.

Field names below (playerFullName/playerName, earnedRunAverage/era) are
cross-referenced from multiple independent community sources, but — same
as every other integration in this project — if MLB changes their
response shape, this fails with a diagnostic printout rather than silently
returning nothing, so a mismatch is one round-trip to fix, not a mystery.
"""
import requests

import config
from clients.name_utils import normalize_name


class MLBStatsAPIClient:
    SCHEDULE_BASE = "https://statsapi.mlb.com/api/v1"
    STATS_BASE = "https://bdfed.stitch.mlbinfra.com/bdfed/stats/player"

    def __init__(self, mock_mode: bool = None):
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode

    def get_schedule(self, date_str: str) -> list:
        """
        Returns a flat list of raw game dicts for the given date (already
        unwrapped from the 'dates' -> 'games' nesting MLB's API uses).
        Each game includes probable pitchers via the hydrate parameter, so
        no separate call is needed for starter info.
        """
        if self.mock_mode:
            return self._mock_schedule()

        params = {
            "sportId": 1,
            "date": date_str,
            "hydrate": "team,linescore,probablePitcher",
        }
        try:
            resp = requests.get(f"{self.SCHEDULE_BASE}/schedule", params=params,
                                 timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            print(f"[mlbstatsapi] WARNING: schedule request failed ({type(e).__name__}: {e}). "
                  f"No games will be ingested this run.")
            return []

        if resp.status_code != 200:
            print(f"[mlbstatsapi] WARNING: {resp.status_code} fetching schedule for {date_str}.")
            return []

        data = resp.json()
        games = []
        for d in data.get("dates", []):
            games.extend(d.get("games", []))

        if not games and data.get("totalGames", 0) == 0:
            pass  # genuinely no games that day (off day) — not an error
        elif not games:
            print(f"[mlbstatsapi] WARNING: schedule response didn't match the expected "
                  f"'dates[].games[]' shape. Top-level keys: {list(data.keys())}.")
        return games

    @staticmethod
    def is_game_final(game: dict) -> bool:
        """True if a game dict (from get_schedule) represents a completed game."""
        state = game.get("status", {}).get("abstractGameState", "")
        detailed = game.get("status", {}).get("detailedState", "")
        return state == "Final" or detailed in ("Final", "Game Over", "Completed Early")

    @staticmethod
    def extract_final_score(game: dict):
        """
        Returns (home_score, away_score) or (None, None) if not available.
        Tries teams.{home,away}.score first (present once a game is final
        with the 'team'/'linescore' hydrates already requested by
        get_schedule), falling back to the linescore totals if needed.
        """
        home_score = game.get("teams", {}).get("home", {}).get("score")
        away_score = game.get("teams", {}).get("away", {}).get("score")
        if home_score is not None and away_score is not None:
            return int(home_score), int(away_score)

        linescore = game.get("linescore", {}) or {}
        ls_teams = linescore.get("teams", {})
        home_runs = ls_teams.get("home", {}).get("runs")
        away_runs = ls_teams.get("away", {}).get("runs")
        if home_runs is not None and away_runs is not None:
            return int(home_runs), int(away_runs)

        return None, None

    def get_pitching_era_lookup(self, season: str) -> dict:
        """
        Lookup of real season ERA for all qualifying pitchers. Returns a
        dict with two keys:
          - "by_id": {playerId (int): era} — PRIMARY lookup. playerId is
            MLB's own numeric player ID, present both here and on the
            schedule endpoint's probablePitcher object, so joining on it
            is exact — no string-similarity guessing involved.
          - "by_name": {normalize_name(name): era} — FALLBACK ONLY, used
            if a playerId is ever missing on one side. Name matching
            across formatting differences (suffixes, accents, nicknames)
            is inherently lossy, which is what caused a prior bug where
            an unrelated pitcher was suggested as a "close match" for a
            missing one purely on name-string similarity.

        Paginates properly rather than trusting a single large `limit`
        value — live testing showed the endpoint returning only ~63
        pitchers despite requesting limit=1500, meaning it caps page size
        server-side regardless of the requested limit. Loops with a
        moderate page size until a short page signals the end, instead of
        assuming one big request covers the whole league.
        """
        if self.mock_mode:
            return self._mock_era_lookup()

        # Confirmed via live diagnostic output: the real field is 'era'.
        # 'earnedRunAverage' never appears in the actual response (that name
        # is only used as the sortStat query param, not a result field) —
        # kept as a harmless fallback in case a future response shape adds it.
        NAME_CANDIDATES = ["playerFullName", "playerName"]
        ERA_CANDIDATES = ["era", "earnedRunAverage"]
        ID_CANDIDATES = ["playerId"]
        PAGE_SIZE = 100
        MAX_PAGES = 20  # safety cap: up to 2000 pitchers, comfortably more than a season's pool

        lookup_by_id = {}
        lookup_by_name = {}
        diagnostic_shown = False
        offset = 0
        total_seen = 0

        for page_num in range(MAX_PAGES):
            params = {
                "stitch_env": "prod",
                "season": season,
                "sportId": 1,
                "stats": "season",
                "group": "pitching",
                "gameType": "R",
                "playerPool": "ALL",  # without this, the endpoint appears to default to a
                # restricted subset rather than the full league — live testing showed
                # only 63 pitchers returned (missing known qualified starters) without it
                "limit": PAGE_SIZE,
                "offset": offset,
                "sortStat": "earnedRunAverage",
                "order": "asc",
            }
            try:
                resp = requests.get(self.STATS_BASE, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
            except requests.RequestException as e:
                print(f"[mlbstatsapi] WARNING: pitching stats request failed "
                      f"({type(e).__name__}: {e}) at offset={offset}. Stopping pagination; "
                      f"partial ERA data may result (had {total_seen} pitchers so far).")
                break

            if resp.status_code != 200:
                print(f"[mlbstatsapi] WARNING: {resp.status_code} fetching pitching stats "
                      f"at offset={offset}. Stopping pagination (had {total_seen} pitchers so far).")
                break

            data = resp.json()
            stats = data.get("stats", [])
            if not stats:
                if page_num == 0:
                    print(f"[mlbstatsapi] WARNING: zero pitching stats returned for {season} on "
                          f"the first page. Top-level response keys: {list(data.keys())}.")
                break

            for s in stats:
                name = next((s.get(k) for k in NAME_CANDIDATES if s.get(k)), None)
                era_raw = next((s.get(k) for k in ERA_CANDIDATES if s.get(k) is not None), None)
                player_id_raw = next((s.get(k) for k in ID_CANDIDATES if s.get(k) is not None), None)
                era = self._to_float(era_raw)
                if era is None or (name is None and player_id_raw is None):
                    if not diagnostic_shown:
                        print(f"[mlbstatsapi] NOTE: one stats entry had no usable name/era value "
                              f"(likely a pitcher with 0 recorded innings this season, whose 'era' "
                              f"field comes back null/undefined rather than 0.00 — normal, not an "
                              f"error). Keys present on that entry: {list(s.keys())}.")
                        diagnostic_shown = True
                    continue
                if player_id_raw is not None:
                    try:
                        lookup_by_id[int(player_id_raw)] = era
                    except (TypeError, ValueError):
                        pass  # unexpected non-numeric playerId — fall through to name-only
                if name:
                    lookup_by_name[normalize_name(name)] = era
                total_seen += 1

            if len(stats) < PAGE_SIZE:
                break  # last page
            offset += PAGE_SIZE

        print(f"[mlbstatsapi] Pulled {total_seen} pitchers' ERA ({len(lookup_by_id)} with a "
              f"usable playerId) across {page_num + 1} page(s) for {season} regular season.")

        # A full-season MLB pitching pool is typically 300-500+ pitchers with
        # at least some innings by mid-season. A count well below that with
        # known qualified starters missing (as seen in testing) suggests the
        # query itself is scoped wrong somehow — not a pagination issue,
        # since pagination correctly detected a short page. Sample the
        # actual contents so the real cause is visible instead of guessed.
        if 0 < total_seen < 200:
            sample = list(lookup_by_name.items())[:15]
            print(f"[mlbstatsapi] NOTE: {total_seen} is low for a full pitching pool — "
                  f"sampling what was actually returned to help diagnose: {sample}")

        return {"by_id": lookup_by_id, "by_name": lookup_by_name}

    @staticmethod
    def _to_float(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    # -- Mock data -----------------------------------------------------------

    def _mock_schedule(self):
        return [
            {
                "gamePk": 10001,
                "gameDate": "2026-07-06T23:05:00Z",
                "status": {"detailedState": "Scheduled"},
                "venue": {"name": "Yankee Stadium"},
                "teams": {
                    "home": {
                        "team": {"name": "New York Yankees"},
                        "probablePitcher": {"id": 20001, "fullName": "Gerrit Cole"},
                    },
                    "away": {
                        "team": {"name": "Boston Red Sox"},
                        "probablePitcher": {"id": 20002, "fullName": "Brayan Bello"},
                    },
                },
            },
            {
                "gamePk": 10002,
                "gameDate": "2026-07-07T02:10:00Z",
                "status": {"detailedState": "Scheduled"},
                "venue": {"name": "Dodger Stadium"},
                "teams": {
                    "home": {
                        "team": {"name": "Los Angeles Dodgers"},
                        "probablePitcher": {"id": 20003, "fullName": "Yoshinobu Yamamoto"},
                    },
                    "away": {
                        "team": {"name": "San Francisco Giants"},
                        "probablePitcher": {"id": 20004, "fullName": "Logan Webb"},
                    },
                },
            },
        ]

    def _mock_era_lookup(self):
        # IDs match the probablePitcher ids used in _mock_schedule above,
        # so the by_id join path is exercised in mock mode too.
        return {
            "by_id": {
                20001: 3.10,   # Gerrit Cole
                20002: 4.25,   # Brayan Bello
                20003: 2.85,   # Yoshinobu Yamamoto
                20004: 3.02,   # Logan Webb
            },
            "by_name": {
                normalize_name("Gerrit Cole"): 3.10,
                normalize_name("Brayan Bello"): 4.25,
                normalize_name("Yoshinobu Yamamoto"): 2.85,
                normalize_name("Logan Webb"): 3.02,
            },
        }
