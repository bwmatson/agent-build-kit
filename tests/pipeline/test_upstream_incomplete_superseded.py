"""A closed original of a split does not hold an acceptance or narrow unit as an upstream that
went back; its pieces do (spec: acceptance-follow)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    UnitState,
)
from agent_build_kit.pipeline.wiring import build_upstream_incomplete
from tests.factories import stored_unit
from tests.pipeline.test_earlier_units_skip_superseded import FOLLOWER, ORIGINAL, change

SECOND = "feature/4-s2"


def held_by(tmp_path: Path, extra: Sequence[StoredUnit] = (), **kwargs) -> tuple[Cause, str] | None:
    """Why the running follower is held, over the change `change` builds and the `extra` units."""
    store = UnitStore(tmp_path / "units.json")
    units = [*change(**kwargs), *extra]
    store.import_units(units)
    for unit in units:
        store.set_state(unit.id, unit.state)
    store.set_state(FOLLOWER, RUNNING)
    return build_upstream_incomplete(store)(store.get(FOLLOWER))


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
@pytest.mark.parametrize("second", [IN_REVIEW, MERGED])
def test_finished_pieces_leave_the_follower_unheld(
    tmp_path: Path, flag: str, second: UnitState
) -> None:
    assert held_by(tmp_path, flag=flag, second=second) is None


@pytest.mark.parametrize("second", [PLANNED, RUNNING, FAILED, HELD])
def test_a_piece_that_is_not_done_still_holds_the_follower(
    tmp_path: Path, second: UnitState
) -> None:
    reason = held_by(tmp_path, second=second)

    assert reason is not None
    assert reason[0] is Cause.UPSTREAM_WENT_BACK
    assert SECOND in reason[1]
    assert ORIGINAL not in reason[1].replace("feature/4-s", "")


def test_a_closed_unit_with_no_pieces_still_holds_the_follower(tmp_path: Path) -> None:
    unreplaced = stored_unit("feature/5", change="feature", state=CLOSED)

    reason = held_by(tmp_path, [unreplaced])

    assert reason is not None
    assert "feature/5" in reason[1]
    assert ORIGINAL not in reason[1].replace("feature/4-s", "")
