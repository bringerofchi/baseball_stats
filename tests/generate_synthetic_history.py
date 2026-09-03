"""
One-off synthetic data generator — NOT part of the shipped system.
Populates ~300 fake settled games with randomized signals and outcomes so
the research layer (threshold optimizer, combination analyzer, edge
scorer) can be exercised end-to-end before being pointed at real data.
Deleted / not included in the final deliverable.
"""
import random
from datetime import date, timedelta

import sys
sys.path.append(".")
from db.database import connection, upsert
from pipeline.evaluate import store_outcome

random.seed(42)

TEAMS = ["NYY", "BOS", "LAD", "SF", "HOU", "ATL", "PHI", "TOR"]

with connection() as conn:
    start = date(2025, 4, 1)
    for i in range(300):
        game_date = start + timedelta(days=i // 4)
        date_str = game_date.isoformat()
        game_id = f"g{i:04d}"
        home, away = random.sample(TEAMS, 2)

        upsert(conn, "games", {
            "game_id": game_id, "date": date_str, "home_team": home, "away_team": away,
            "stadium": f"{home} Park", "weather_temp": 75.0, "weather_wind_speed": 6.0,
            "weather_wind_direction": "S", "weather_precipitation": 0.0, "status": "final",
        }, conflict_keys=["game_id"])

        # Simulate a "true" underlying edge for testing: xERA gap correlates
        # weakly+noisily with home win, so threshold search has something
        # real (if modest) to find, plus lots of noise.
        home_xera = random.uniform(2.8, 5.0)
        away_xera = random.uniform(2.8, 5.0)
        upsert(conn, "starters", {
            "game_id": game_id, "home_pitcher_name": "P1", "away_pitcher_name": "P2",
            "home_ERA": home_xera, "away_ERA": away_xera, "home_xERA": home_xera, "away_xERA": away_xera,
            "home_days_rest": 4, "away_days_rest": 4,
            "pitch_count_last_start_home": 90, "pitch_count_last_start_away": 90,
        }, conflict_keys=["game_id"])

        # Bullpen fatigue: random, weakly predictive
        bp_home = random.uniform(2, 14)
        bp_away = random.uniform(2, 14)
        upsert(conn, "team_form", {
            "team": home, "date": date_str, "last_5_runs_scored_avg": 4.5, "last_5_runs_allowed_avg": 4.2,
            "bullpen_innings_last_3_days": bp_home, "win_streak": 0, "loss_streak": 0,
            "last_game_margin": random.randint(-8, 8), "extra_innings_last_game": random.choice([0, 0, 0, 1]),
        }, conflict_keys=["team", "date"])
        upsert(conn, "team_form", {
            "team": away, "date": date_str, "last_5_runs_scored_avg": 4.5, "last_5_runs_allowed_avg": 4.2,
            "bullpen_innings_last_3_days": bp_away, "win_streak": 0, "loss_streak": 0,
            "last_game_margin": random.randint(-8, 8), "extra_innings_last_game": random.choice([0, 0, 0, 1]),
        }, conflict_keys=["team", "date"])

        # Odds: home moneyline roughly reflects a base 50/50 with vig, plus noise
        ml_home = random.choice([-180, -150, -130, -110, 100, 120, 150, 180])
        ml_away = -110 if ml_home < 0 else -130
        closing_shift = random.choice([-15, -10, 0, 0, 10, 15])
        upsert(conn, "odds", {
            "game_id": game_id, "sportsbook": "mock_book",
            "opening_moneyline_home": ml_home, "opening_moneyline_away": ml_away,
            "closing_moneyline_home": ml_home + closing_shift, "closing_moneyline_away": ml_away - closing_shift,
            "opening_total": 8.5, "closing_total": 8.5,
        }, conflict_keys=["game_id", "sportsbook"])

        # Outcome: home win probability nudged by xERA gap (small real signal) + noise
        xera_gap = away_xera - home_xera  # positive favors home
        home_win_prob = 0.5 + 0.05 * xera_gap + random.uniform(-0.3, 0.3)
        home_win_prob = max(0.05, min(0.95, home_win_prob))
        home_wins = random.random() < home_win_prob
        home_score = random.randint(2, 9)
        away_score = random.randint(2, 9)
        if home_wins and away_score >= home_score:
            home_score, away_score = away_score + 1, home_score
        elif not home_wins and home_score >= away_score:
            home_score, away_score = away_score, home_score + 1
        store_outcome(conn, game_id, home_score, away_score)

print("Synthetic dataset generated: 300 games.")
