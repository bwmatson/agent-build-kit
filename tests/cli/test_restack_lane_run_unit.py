"""The lane's worker goes on into the unit's run after a move that does not finish its work,
and ends as a build worker's run ends (spec: unit-scheduling).

A unit in review is moved by a fake stack move that leaves it as a conflict, a deferral or a
clean move does; the run is `scripted_engine`'s: the `run` of what `build_runner` returns, in
the thread that calls it. What is read is which thread and which lock the run had.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.pause import pause_in_force
from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.pipeline.workspaces import branch_held, branch_lock
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.runtimes import AgentRateLimited
from tests.conftest import make_installation
from tests.factories import git, init_repo, new_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

MOVED = "second/1"
CLEAN = "third/1"


class Scene:
    """Two units in review whose branches are behind `main`. The stack move leaves `second/1`
    as `leaves` says and `third/1` as it was; a run of a unit notes where it ran and with what
    held, and then does `ends`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
            },
            project_limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit(MOVED), new_unit(CLEAN)])
        repo = init_repo(self.inst.checkouts["app"])
        (repo / "a.txt").write_text("a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "a")
        for unit in (MOVED, CLEAN):
            git(repo, "branch", f"spec/{unit}")
            self.store.set_state(unit, IN_REVIEW, pr=9, branch=f"spec/{unit}")
        (repo / "b.txt").write_text("b\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "b")
        self.leaves = Cause.RESTACK_CONFLICT
        self.ran: list[str] = []
        self.threads: list[str] = []
        self.held: list[bool] = []
        self.flagged: list[bool] = []
        self.moves: list[str] = []
        self.ends: Any = lambda unit: RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=9)
        for name, step in {
            "fetch_all": lambda inst: None,
            "has_identity": lambda inst, repo: True,
            "build_runner": lambda unit, **kwargs: self,
            "build_restack": lambda **kwargs: self.move,
            "owed_units": lambda inst, units: {MOVED, CLEAN},
        }.items():
            monkeypatch.setattr(cli, name, step)

    def move(self, **kwargs: Any) -> None:
        """The stack move: a conflict or a deferral leaves the unit planned for its run."""
        child = kwargs["child"]
        self.moves.append(child.id)
        if child.id == MOVED:
            self.store.set_state(child.id, PLANNED, cause=self.leaves, branch=f"spec/{child.id}")

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.ran.append(unit.id)
        self.threads.append(threading.current_thread().name)
        self.held.append(branch_held(branch_name(unit), root=self.inst.state_dir / "locks"))
        self.flagged.append(self.store.get(unit.id).moved_base_run)
        return self.ends(unit)

    def lane_moves(self) -> RestackLanes:
        with cli.build_restack_lane(self.inst, self.store) as lanes:
            lanes.scan(self.store.all())
        return lanes


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


@pytest.mark.parametrize("cause", [Cause.RESTACK_CONFLICT, Cause.RESTACK_DEFERRED])
def test_a_move_left_for_its_run_is_followed_by_the_run_in_the_same_lane_worker(
    scene: Scene, cause: Cause
) -> None:
    scene.leaves = cause

    scene.lane_moves()

    assert scene.moves.count(MOVED) == 1
    assert scene.ran == [MOVED]
    assert scene.threads == ["restack"], "a worker of the lane, not a build worker"
    assert scene.held == [True], "the run holds the unit's branch"


def test_a_clean_move_of_an_approved_head_ends_with_the_move_and_makes_no_run(
    scene: Scene,
) -> None:
    scene.lane_moves()

    assert sorted(scene.moves) == [MOVED, CLEAN]
    assert CLEAN not in scene.ran
    assert scene.store.get(CLEAN).state == IN_REVIEW
    assert scene.ran == [MOVED], "only the move that left its unit planned goes on into a run"


def test_the_run_opens_the_units_run_log(scene: Scene) -> None:
    scene.lane_moves()

    assert scene.store.get(MOVED).run_log != ""
    assert scene.store.get(CLEAN).run_log == ""


def test_a_run_the_usage_window_refused_pauses_the_pipeline_as_a_build_worker_does(
    scene: Scene,
) -> None:
    def refused(unit: StoredUnit) -> RunOutcome:
        raise RateLimited("usage limit reached")

    scene.ends = refused

    scene.lane_moves()

    assert pause_in_force(scene.inst.state_dir)


def test_a_run_whose_network_is_down_parks_the_unit_at_its_step(scene: Scene) -> None:
    def parked(unit: StoredUnit) -> RunOutcome:
        raise HostUnavailable("create_pr", "HTTP 500", 3)

    scene.ends = parked

    scene.lane_moves()

    stored = scene.store.get(MOVED)
    assert (stored.state, stored.cause) == (PLANNED, Cause.HOST_UNAVAILABLE)


def test_a_run_that_fails_leaves_the_unit_failed_with_its_error(scene: Scene) -> None:
    def fails(unit: StoredUnit) -> RunOutcome:
        raise RuntimeError("the checks cannot start")

    scene.ends = fails

    scene.lane_moves()

    stored = scene.store.get(MOVED)
    assert (stored.state, stored.cause) == (FAILED, Cause.FAILED)
    assert "the checks cannot start" in stored.history[-1]["note"]


def test_a_run_that_cannot_go_on_is_held_for_a_person(scene: Scene) -> None:
    def unsupported(unit: StoredUnit) -> RunOutcome:
        raise ProfileUnsupported("no such profile")

    scene.ends = unsupported

    scene.lane_moves()

    stored = scene.store.get(MOVED)
    assert (stored.state, stored.cause) == (HELD, Cause.TOOLCHAIN)


def test_a_run_is_flagged_the_lanes_while_it_goes(scene: Scene) -> None:
    scene.lane_moves()

    assert scene.flagged == [True]


def test_a_run_that_finds_its_branch_held_is_not_made_and_the_unit_is_not_flagged(
    scene: Scene,
) -> None:
    scene.store.set_state(MOVED, PLANNED, cause=Cause.RESTACK_CONFLICT, branch=f"spec/{MOVED}")

    with branch_lock(f"spec/{MOVED}", root=scene.inst.state_dir / "locks"):
        with cli.build_restack_lane(scene.inst, scene.store) as lanes:
            lanes.hand_over(scene.store.get(MOVED), claimed=False)

    assert scene.ran == []
    assert scene.store.get(MOVED).moved_base_run is False


def test_a_run_whose_unit_a_tab_holds_is_not_made_and_the_unit_is_not_flagged(
    scene: Scene,
) -> None:
    scene.store.set_state(MOVED, PLANNED, cause=Cause.RESTACK_CONFLICT, branch=f"spec/{MOVED}")
    assert Leases(lease_dir(scene.inst.state_dir)).take(MOVED, "tab:a")

    with cli.build_restack_lane(scene.inst, scene.store) as lanes:
        lanes.hand_over(scene.store.get(MOVED), claimed=False)

    assert scene.ran == []
    assert scene.store.get(MOVED).moved_base_run is False


def test_a_refusal_the_move_met_does_not_drop_the_run_the_unit_is_later_owed(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refusing(inst: Installation, *, gated: bool, refused: Any) -> Any:
        def move(path: Path, *args: Any, **kwargs: Any) -> None:
            refused(kwargs["moving_unit"], None)
            raise AgentRateLimited("usage limit reached")

        return move

    monkeypatch.setattr(cli, "build_turned_move", refusing)
    scene.store.set_state(MOVED, RUNNING, branch=f"spec/{MOVED}", cause=Cause.BASE_CHANGED)
    with cli.build_restack_lane(scene.inst, scene.store) as lanes:
        lanes.hand_over(scene.store.get(MOVED))
        lanes.drain()
        assert scene.ran == [], "the refused move is left deferred, and no run follows it"

        scene.store.set_moved_base_run(MOVED, True)
        lanes.hand_over(scene.store.get(MOVED), claimed=False)

    assert scene.ran == [MOVED]


def test_a_run_in_the_lane_asks_the_build_pool_for_no_worker(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Counting(ThreadPoolExecutor):
        submitted = 0

        def submit(self, *args: Any, **kwargs: Any) -> Any:
            Counting.submitted += 1
            return super().submit(*args, **kwargs)

    monkeypatch.setattr(cli, "ThreadPoolExecutor", Counting)

    scene.lane_moves()

    assert scene.ran == [MOVED]
    assert Counting.submitted == 0
