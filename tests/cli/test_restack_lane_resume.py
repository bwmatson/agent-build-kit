"""A moved-base run a process lost or a usage pause interrupted is resumed by the lane, not
offered to a build worker (spec: unit-scheduling).

The unit is `running` with the moved-base flag set and a thread (`repo_behind` says every
unit has one), no lease and a free branch lock. The run is `scripted_engine`'s: the `run` of
what `build_runner` returns, in the thread that calls it.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import new_unit
from tests.restack_lane_fakes import repo_behind

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "feature/3"
BRANCH = "spec/feature/3"


class Scene:
    """`feature/3` stopped `running` in its review step, flagged or not as a killed process
    leaves it."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = repo_behind(tmp_path, monkeypatch)
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit(UNIT)])
        self.store.set_state(UNIT, RUNNING, branch=BRANCH, cause=Cause.RESTACK_CONFLICT)
        self.ran: list[str] = []
        self.threads: list[str] = []
        monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: self)

    def flag(self, flagged: bool = True) -> None:
        self.store.set_moved_base_run(UNIT, flagged)

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.ran.append(unit.id)
        self.threads.append(threading.current_thread().name)
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=9)

    def owed(self) -> set[str]:
        return set(cli.owed_units(self.inst, self.store.all()))

    def offered(self) -> list[str]:
        units = cli.resumable_units(self.inst, self.store.all(), only=frozenset())
        return [unit.id for unit in units]

    def lane_scans(self) -> None:
        with cli.build_restack_lane(self.inst, self.store) as lanes:
            lanes.scan(self.store.all())


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_flagged_running_unit_is_the_lanes_and_an_unflagged_one_a_build_workers(
    scene: Scene,
) -> None:
    scene.flag(False)
    assert scene.offered() == [UNIT]
    assert UNIT not in scene.owed()

    scene.flag()

    assert UNIT in scene.owed(), "the lane's scan lists it"
    assert scene.offered() == [], "and no build worker is offered it"


def test_the_lane_resumes_a_flagged_unit_at_its_node_and_a_build_worker_never_does(
    scene: Scene,
) -> None:
    scene.flag()

    scene.lane_scans()

    assert scene.ran == [UNIT]
    assert scene.threads == ["restack"]
    assert scene.offered() == []


def test_a_held_branch_leaves_the_flagged_unit_owed_until_it_is_free(scene: Scene) -> None:
    scene.flag()

    with branch_lock(BRANCH, root=scene.inst.state_dir / "locks"):
        scene.lane_scans()
        assert scene.ran == []
        assert scene.offered() == [], "still the lane's, not a build worker's"

    scene.lane_scans()

    assert scene.ran == [UNIT]


def test_a_flag_left_by_a_killed_process_is_resumed_by_the_next_scan_in_the_lane(
    scene: Scene, tmp_path: Path
) -> None:
    scene.flag()
    reopened = UnitStore(tmp_path / "units.json")
    assert reopened.get(UNIT).moved_base_run, "the flag survives the process that set it"

    scene.lane_scans()

    assert scene.ran == [UNIT]
    assert scene.threads == ["restack"]


def test_a_lane_that_met_the_held_branch_runs_the_flagged_unit_when_it_is_free(
    scene: Scene,
) -> None:
    scene.flag()

    with cli.build_restack_lane(scene.inst, scene.store) as lanes:
        with branch_lock(BRANCH, root=scene.inst.state_dir / "locks"):
            lanes.hand_over(scene.store.get(UNIT), claimed=False)
            lanes.drain()
        assert scene.ran == []

        lanes.scan(scene.store.all())
        lanes.drain()

    assert scene.ran == [UNIT]
