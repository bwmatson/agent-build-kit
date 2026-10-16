"""A held unit's state is stored as text, and no node writes a type the checkpoint blocks.

Each path that ends in `BuildPath.hold()` is driven with the fake runner, and
what the nodes wrote is read from the checkpoint file itself, and
the library's own report of what it blocks is listened to (it warns only once per process).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.pipeline.units import PLANNED
from tests.checkpoint_types import (
    blocked_in,
    blocked_on_load,
    blocked_while_reading,
    node_updates,
    state_from_updates,
)
from tests.factories import unit
from tests.graph.checkpoint_reads import read_back
from tests.graph.test_hold_causes import HOLD_PATHS, Held, fresh

HOLDS = [h for h, _ in HOLD_PATHS]
HOLD_IDS = [h.__name__ for h in HOLDS]
THREAD = unit().id


def held_unit(tmp_path: Path, hold: Held) -> Path:
    hold(tmp_path, fresh(tmp_path))
    return unit_graphs_path(tmp_path / "state")


@pytest.mark.parametrize("hold", HOLDS, ids=HOLD_IDS)
def test_a_held_unit_stores_its_state_as_text(tmp_path: Path, hold: Held) -> None:
    db = held_unit(tmp_path, hold)

    stored = [value for _, field, value in node_updates(db, THREAD) if field == "hold_state"]

    assert stored, "the hold wrote a state"
    assert all(type(value) is str for value in stored)
    assert PLANNED.value in stored


@pytest.mark.parametrize("hold", HOLDS, ids=HOLD_IDS)
def test_no_node_writes_a_type_the_checkpoint_blocks(tmp_path: Path, hold: Held) -> None:
    assert blocked_in(node_updates(held_unit(tmp_path, hold), THREAD)) == []


@pytest.mark.parametrize("hold", HOLDS, ids=HOLD_IDS)
def test_a_populated_state_carrying_the_nodes_values_encodes_no_blocked_type(
    tmp_path: Path, hold: Held
) -> None:
    state = state_from_updates(node_updates(held_unit(tmp_path, hold), THREAD))

    assert blocked_on_load(state) == set()


@pytest.mark.parametrize("hold", HOLDS, ids=HOLD_IDS)
def test_reading_a_held_unit_back_blocks_no_type(tmp_path: Path, hold: Held) -> None:
    db = held_unit(tmp_path, hold)

    with blocked_while_reading() as blocked:
        snapshot = read_back(db, THREAD)

    assert blocked == set()
    assert snapshot.values["hold_state"] == PLANNED.value
