"""A moved-base run the lane starts is one attempt at the tip of the unit's base
(spec: unit-scheduling)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import CLOSED, RUNNING
from agent_build_kit.pipeline.usage_guard import Interrupted
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.moved_base_attempts_scene import BRANCH, PUSHED, UNIT, Attempts

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Attempts:
    return Attempts(tmp_path, monkeypatch)


def test_a_first_run_at_a_tip_records_attempt_one_with_the_tip_the_head_and_the_time(
    scene: Attempts,
) -> None:
    scene.scan()

    stored = scene.unit
    assert scene.ran == [UNIT]
    assert stored.conflict_attempts == 1
    assert stored.conflict_tip == scene.tip()
    assert stored.conflict_head == PUSHED
    assert stored.conflict_at is not None


def test_a_second_run_at_the_same_tip_is_attempt_two(scene: Attempts) -> None:
    scene.scan()

    scene.run_again()

    assert scene.ran == [UNIT, UNIT]
    assert scene.unit.conflict_attempts == 2
    assert scene.unit.conflict_tip == scene.tip()


def test_a_new_tip_starts_the_count_at_one(scene: Attempts) -> None:
    scene.scan()
    scene.run_again()
    first = scene.tip()

    scene.base_moves()
    scene.run_again()

    assert scene.tip() != first
    assert scene.unit.conflict_tip == scene.tip()
    assert scene.unit.conflict_attempts == 1


def test_a_run_resumed_with_the_flag_set_at_the_same_tip_is_not_counted_again(
    scene: Attempts,
) -> None:
    scene.store.record_conflict_attempt(
        UNIT, tip=scene.tip(), head=PUSHED, attempts=1, at=datetime.now(UTC)
    )
    scene.store.set_state(UNIT, RUNNING, branch=BRANCH, cause=Cause.RESTACK_CONFLICT)
    scene.store.set_moved_base_run(UNIT, True)

    scene.scan()

    assert scene.ran == [UNIT], "the lane's scan resumes the interrupted run"
    assert scene.unit.conflict_attempts == 1

    scene.run_again()

    assert scene.unit.conflict_attempts == 2, "the next start at that tip is the second"


def test_a_branch_held_by_another_run_is_not_an_attempt(scene: Attempts) -> None:
    with branch_lock(BRANCH, root=scene.inst.state_dir / "locks"):
        scene.scan()

    assert scene.ran == []
    assert scene.unit.conflict_attempts == 0

    scene.run_again()

    assert scene.unit.conflict_attempts == 1, "the run that goes ahead is the first attempt"


def test_a_usage_pause_before_the_first_agent_call_is_not_an_attempt_and_its_resume_is(
    scene: Attempts,
) -> None:
    def paused(unit: StoredUnit) -> None:
        scene.leaves_running(unit)
        raise Interrupted("usage window full: not started")

    scene.ends = paused

    scene.scan()
    assert scene.unit.state == RUNNING
    assert scene.unit.moved_base_run, "left flagged, for the lane's resume"
    assert scene.unit.conflict_attempts == 0

    scene.ends = scene.settles
    scene.scan()

    assert scene.ran == [UNIT, UNIT], "the lane's scan resumed the flagged run"
    assert scene.unit.conflict_attempts == 1, "the run that goes ahead is the first attempt"


def test_a_run_cut_off_after_an_agent_call_stays_an_attempt_and_its_resume_is_the_same_one(
    scene: Attempts,
) -> None:
    def killed(unit: StoredUnit) -> None:
        scene.transcript("the port agent said something")
        scene.leaves_running(unit)
        raise Interrupted("claude was killed by signal 9")

    scene.ends = killed

    scene.scan()
    assert scene.unit.conflict_attempts == 1

    scene.ends = scene.settles
    scene.scan()

    assert scene.ran == [UNIT, UNIT]
    assert scene.unit.conflict_attempts == 1, "the resumed run is the same attempt"


def test_a_run_that_found_nothing_owed_is_not_an_attempt(scene: Attempts) -> None:
    scene.store.set_state(UNIT, CLOSED)
    with cli.build_restack_lane(scene.inst, scene.store) as lanes:
        lanes.hand_over(scene.unit, claimed=False)

    assert scene.ran == []
    assert scene.unit.conflict_attempts == 0

    scene.run_again()

    assert scene.unit.conflict_attempts == 1, "the first run that goes ahead is the first"


def test_an_attempt_the_conflict_handler_made_at_the_same_tip_counts_in_the_lanes_total(
    scene: Attempts,
) -> None:
    scene.store.record_conflict_attempt(
        UNIT, tip=scene.tip(), head=PUSHED, attempts=2, at=datetime.now(UTC)
    )

    scene.scan()

    assert scene.unit.conflict_attempts == 3
