import sys
sys.path.insert(0, ".")
from db.database import connection

with connection() as conn:
    print("=== games provenance (2026-08-01) ===")
    rows = conn.execute("""SELECT game_id, home_team, away_team, data_source,
        timestamp_collected, collection_stage, data_version, collection_status
        FROM games WHERE date = '2026-08-01' LIMIT 3""").fetchall()
    for r in rows:
        print(dict(r))

    print()
    print("=== odds provenance (sample, 2026-08-01 games) ===")
    rows = conn.execute("""SELECT o.game_id, o.sportsbook, o.data_source,
        o.timestamp_collected, o.collection_stage, o.data_version
        FROM odds o JOIN games g ON o.game_id = g.game_id
        WHERE g.date = '2026-08-01' LIMIT 3""").fetchall()
    for r in rows:
        print(dict(r))

    print()
    print("=== starters provenance (sample, 2026-08-01 games) ===")
    rows = conn.execute("""SELECT s.game_id, s.data_source,
        s.timestamp_collected, s.collection_stage, s.data_version
        FROM starters s JOIN games g ON s.game_id = g.game_id
        WHERE g.date = '2026-08-01' LIMIT 3""").fetchall()
    for r in rows:
        print(dict(r))
