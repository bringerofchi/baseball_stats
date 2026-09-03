"""
Registers the three original edges (sp_mismatch, bullpen_fatigue,
overreaction) into the plug-in registry, as thin read-only adapters over
the `edges` table that pipeline/edges.py already populates.

This file is the ONLY place that bridges the original hardcoded pipeline
to the new plug-in framework — pipeline/edges.py itself is untouched.
Import this module once (research modules do it automatically) before
calling anything that needs list_edges() to include the original three.
"""
import sys

sys.path.append(".")

from research.edge_registry import register_edge, get_edge


def _compute_sp_mismatch(conn, game_id):
    row = conn.execute("SELECT sp_edge_score FROM edges WHERE game_id=?", (game_id,)).fetchone()
    if not row or row["sp_edge_score"] is None:
        return None
    val = row["sp_edge_score"]
    side = "home" if val > 0 else "away"
    return {"signal_value": abs(val), "side": side}


def _compute_bullpen_fatigue(conn, game_id):
    row = conn.execute(
        "SELECT bullpen_fatigue_index_home, bullpen_fatigue_index_away FROM edges WHERE game_id=?",
        (game_id,),
    ).fetchone()
    if not row or row["bullpen_fatigue_index_home"] is None or row["bullpen_fatigue_index_away"] is None:
        return None
    diff = row["bullpen_fatigue_index_away"] - row["bullpen_fatigue_index_home"]
    side = "home" if diff > 0 else "away"
    return {"signal_value": abs(diff), "side": side}


def _compute_overreaction(conn, game_id):
    row = conn.execute(
        "SELECT overreaction_flag, overreaction_direction FROM edges WHERE game_id=?",
        (game_id,),
    ).fetchone()
    if not row or not row["overreaction_flag"]:
        return None
    side = "away" if row["overreaction_direction"] == "home_faded" else "home"
    return {"signal_value": 1.0, "side": side}


def register_core_edges():
    if get_edge("sp_mismatch") is None:
        register_edge(
            "sp_mismatch", _compute_sp_mismatch,
            description="Gap between xERA-implied win prob and market-implied win prob",
            value_range=(0.0, 0.30),
        )
    if get_edge("bullpen_fatigue") is None:
        register_edge(
            "bullpen_fatigue", _compute_bullpen_fatigue,
            description="Difference in bullpen fatigue index between teams",
            value_range=(0.0, 15.0),
        )
    if get_edge("overreaction") is None:
        register_edge(
            "overreaction", _compute_overreaction,
            description="Market overreaction to a recent blowout result",
            value_range=(0.0, 1.0),
        )


register_core_edges()
