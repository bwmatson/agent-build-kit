"""A wait recorded on a replaced unit follows its successor instead of ending as a closed
prerequisite (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, UnitState
from tests.factories import new_unit
from tests.wait_end_support import CHILD, Pipeline, pipeline


def failed_on_replaced(
    pipe: Pipeline, successor: UnitState | None, *, waited: tuple[str, ...] = ("x/3",)
) -> None:
    """`CHILD` failed while waiting on `x/3`, which a replan then replaced by `x/5` (state
    `successor`, or no successor when None)."""
    pipe.store.import_units(
        [
            new_unit("x/3", state=UnitState.UNPLANNED, superseded_by=("x/5",) if successor else ()),
            *([new_unit("x/5", state=successor, branch="spec/x/5")] if successor else []),
            new_unit(CHILD, depends_on=("x/3",), waited_on=waited),
        ]
    )
    pipe.store.set_state(CHILD, FAILED, branch=f"spec/{CHILD}", cause=Cause.FAILED)


def test_a_successor_in_review_requeues_the_unit_once_and_records_no_wait_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    failed_on_replaced(pipe, IN_REVIEW)

    pipe.passes(2)

    assert len(pipe.host.deliveries) == 1
    assert pipe.store.get(CHILD).wait_ended == ""


def test_a_successor_still_building_is_the_one_the_record_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    failed_on_replaced(pipe, UnitState.PLANNED)

    pipe.pass_()

    child = pipe.store.get(CHILD)
    assert child.state == FAILED
    assert child.waited_on == ("x/5",)
    assert pipe.host.deliveries == []
    assert child.wait_ended == ""


def test_a_replaced_unit_with_no_successor_ends_the_wait_as_a_closed_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    failed_on_replaced(pipe, None)
    pipe.store.import_units(
        [
            new_unit("y/3", state=UnitState.UNPLANNED, superseded_by=("y/5",)),
            new_unit("y/5", state=IN_REVIEW, branch="spec/y/5"),
        ]
    )
    pipe.store.set_waited_on(CHILD, ("x/3", "y/3"))

    pipe.pass_()

    child = pipe.store.get(CHILD)
    assert child.state == FAILED
    assert child.wait_ended == "x group 3"
    assert pipe.host.deliveries == []
