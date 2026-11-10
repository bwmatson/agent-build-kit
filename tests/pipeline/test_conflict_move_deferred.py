"""A conflict move that could not run now leaves the unit in review owing its restack."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.resolution_lane import owed_a_restack
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.wiring import follow_predecessors
from tests.conflict_event_fakes import PARENT, UNIT, ConflictRig
from tests.factories import stored_unit


def deferred_move(rig: ConflictRig) -> None:
    """What a resolve worker leaves a unit as when its conflict move could not run now."""
    rig.store.set_state(
        UNIT,
        IN_REVIEW,
        note="conflict move deferred: could not run now",
        cause=Cause.RESTACK_DEFERRED,
    )


def owed(rig: ConflictRig) -> bool:
    graph = rig.store.all()
    return owed_a_restack(
        rig.stored(),
        graph,
        holds_base=lambda unit: False,
        held=lambda unit: False,
        leased=lambda unit: False,
    )


def test_a_unit_whose_conflict_move_was_deferred_is_owed_its_restack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    deferred_move(rig)

    assert owed(rig)


def test_follow_predecessors_leaves_a_unit_whose_conflict_move_was_deferred_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    deferred_move(rig)
    # A replan then stacks the unit on a predecessor that keeps the runtime fields it has.
    rig.store.upsert(
        [stored_unit(PARENT, change="parent"), stored_unit(UNIT, depends_on=(PARENT,))]
    )
    # The predecessor is itself moving onto a moved base: the dependent would follow it.
    rig.store.set_state(PARENT, PLANNED, cause=Cause.BASE_CHANGED)

    moved = follow_predecessors(
        rig.store, head=lambda unit: "", claim=lambda unit: nullcontext(), log=rig.logged.append
    )

    stored: StoredUnit = rig.store.get(UNIT)
    assert moved == []
    assert (stored.state, stored.cause) == (IN_REVIEW, Cause.RESTACK_DEFERRED)
