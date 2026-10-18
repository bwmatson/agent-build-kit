"""A replan keeps a started unit's split and gives an unstarted one the new plan's."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests.factories import unit


def test_a_replan_leaves_a_started_units_split_and_moves_an_unstarted_ones(
    tmp_path: Path,
) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert(
        [
            unit("feature/1", change="feature", split="acp"),
            unit("feature/2", change="feature", groups=(2,), split="acp"),
        ]
    )
    store.set_state("feature/1", FAILED, branch="spec/feature/1")

    store.upsert(
        [
            unit("feature/1", change="feature", split="rest"),
            unit("feature/2", change="feature", groups=(2,), split="rest"),
        ]
    )

    assert {u.id: u.split for u in UnitStore(path).all()} == {
        "feature/1": "acp",
        "feature/2": "rest",
    }
