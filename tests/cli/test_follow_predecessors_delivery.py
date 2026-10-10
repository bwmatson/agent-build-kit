"""The pass that parks units in review hands each move to the unit's own thread."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import EventKind, Node
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.graph_driver import fresh, position, tick

PARENT = "add-marker/0"
CHILD = "add-marker/1"
PUSHED = "a" * 40
MOVED = "b" * 40


def test_a_parked_unit_with_a_thread_is_parked_by_an_event_the_thread_waits_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": str(tmp_path / "state"), "worktree_root": str(tmp_path / "trees")},
    )
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    store = recorder.store
    store.upsert([stored_unit(PARENT), stored_unit(CHILD, depends_on=(PARENT,))])
    store.set_state(PARENT, RUNNING, branch="spec/" + PARENT)
    store.record_push(PARENT, PUSHED)
    monkeypatch.setattr(cli, "branch_head", lambda inst, unit: MOVED)

    cli.park_dependents(inst, store)

    parked = store.get(CHILD)
    assert parked.state == PLANNED
    assert parked.cause is Cause.UPSTREAM_WENT_BACK
    where = position(tmp_path)
    assert where.next == (Node.AWAIT_REVIEW,)
    assert where.state is not None
    assert where.state.event is not None
    assert where.state.event.kind is EventKind.UPSTREAM_CHANGED
