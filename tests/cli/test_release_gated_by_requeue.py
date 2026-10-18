"""`release_gated` delivers a planned unit's saved requeue whatever its cause is."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.conftest import make_installation
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLDER = "older/1"
NO_REQUEUE = "bare/1"
WAITING = "waiting/1"
IN_FLIGHT = "flight/1"
RUNNING_UNIT = "running/1"
PARENT = "parent/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )


def test_only_a_planned_unit_with_a_saved_requeue_whose_waits_have_cleared_is_released(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    delivered: list[str] = []
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    monkeypatch.setattr(
        cli,
        "resume_thread",
        lambda inst, unit, kind, **kwargs: delivered.append(unit.id) or object(),
    )
    store.upsert(
        [
            stored_unit(uid, change=uid.partition("/")[0])
            for uid in (OLDER, NO_REQUEUE, IN_FLIGHT, RUNNING_UNIT, PARENT)
        ]
        + [stored_unit(WAITING, change="waiting", depends_on=(PARENT,))]
    )
    for uid, state, cause, requeue in (
        # a record whose cause is not `gated` but which still holds a saved requeue
        (OLDER, PLANNED, Cause.BASE_CHANGED, RequeueReason.RESUME),
        (NO_REQUEUE, PLANNED, Cause.GATED, None),
        (WAITING, PLANNED, Cause.GATED, RequeueReason.RESUME),
        (IN_FLIGHT, PLANNED, Cause.GATED, RequeueReason.RESUME),
        (RUNNING_UNIT, RUNNING, Cause.GATED, RequeueReason.RESUME),
    ):
        store.set_state(uid, state, branch=f"spec/{uid}", cause=cause)
        store.set_gated_requeue(uid, requeue)

    cli.release_gated(inst, store, in_flight=[IN_FLIGHT])

    assert delivered == [OLDER]
    assert store.get(OLDER).gated_requeue is None
    assert store.get(WAITING).gated_requeue is RequeueReason.RESUME
