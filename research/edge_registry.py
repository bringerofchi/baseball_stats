"""
Edge registry — plug-in architecture for edge modules.

Goal: new edge ideas (reverse line movement, park factors, umpire
tendencies, etc.) can be added as independent modules WITHOUT modifying
pipeline/edges.py, pipeline/evaluate.py, or the database schema's core
logic. Each edge module just registers itself here.

A registered edge provides:
  - name: unique string key (matches edge_results.edge_type going forward)
  - compute_fn: function(conn, game_id) -> dict with at least a
                'signal_value' (float) and 'side' ('home'/'away'/'over'/'under'/None)
  - description: human-readable summary
  - value_range: (min, max) expected signal_value range, used by the
                 threshold optimizer to pick a sensible search grid

Existing edges (sp_mismatch, bullpen_fatigue, overreaction) are registered
in pipeline/edges_registration.py so the original pipeline/edges.py stays
untouched and battle-tested.

Usage for adding a new edge:

    from research.edge_registry import register_edge

    def compute_reverse_line_movement(conn, game_id):
        ... your logic ...
        return {"signal_value": 0.04, "side": "home"}

    register_edge(
        name="reverse_line_movement",
        compute_fn=compute_reverse_line_movement,
        description="Line moves opposite of where the betting % is going",
        value_range=(0, 0.15),
    )

That's it — the threshold optimizer, combination analyzer, and edge
scorer all pick it up automatically via list_edges().
"""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class EdgeDefinition:
    name: str
    compute_fn: Callable
    description: str
    value_range: tuple = (0.0, 1.0)


_REGISTRY: dict[str, EdgeDefinition] = {}


def register_edge(name: str, compute_fn: Callable, description: str = "", value_range: tuple = (0.0, 1.0)):
    if name in _REGISTRY:
        raise ValueError(
            f"Edge '{name}' is already registered. Use a unique name, or "
            f"call unregister_edge('{name}') first if you intend to replace it."
        )
    _REGISTRY[name] = EdgeDefinition(name, compute_fn, description, value_range)


def unregister_edge(name: str):
    _REGISTRY.pop(name, None)


def get_edge(name: str) -> Optional[EdgeDefinition]:
    return _REGISTRY.get(name)


def list_edges() -> list:
    return list(_REGISTRY.values())


def clear_registry():
    """Mainly for tests."""
    _REGISTRY.clear()
