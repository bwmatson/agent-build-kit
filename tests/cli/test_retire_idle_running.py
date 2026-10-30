"""`abk retire` takes a `running` unit that nothing holds, refuses one a live process or lease
holds, and agrees with the scheduler on which is which (spec: retire-takes-an-idle-running-unit)."""

from __future__ import annotations

import os

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import UnitState
from tests.attach_driver import leave_lease
from tests.branch_lock_fakes import dead_pid, lock_held_by
from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"
BRANCH = f"spec/{UNIT}"


def running(scene: Scene) -> None:  # noqa: F811
    """A `running` unit whose groups another unit has built, so retiring it needs no reason."""
    scene.add(UNIT, "running")
    scene.built_elsewhere(UNIT)


def test_an_idle_running_unit_is_retired_and_its_history_says_so(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)

    code, out = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    entry = scene.unit(UNIT).history[-1]
    assert entry["by"] == "abk retire"
    assert "idle" in entry["note"]
    assert "idle" in out


def test_a_reason_stays_in_the_note_beside_the_idle_remark(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)

    code, _ = scene.retire(capsys, UNIT, "--reason", "not wanted")

    assert code == 0
    note = scene.unit(UNIT).history[-1]["note"]
    assert "not wanted" in note and "idle" in note


def test_a_running_unit_whose_lock_names_a_process_that_is_gone_counts_as_idle(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)
    lock_held_by(scene.inst, BRANCH, dead_pid())

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert "idle" in scene.unit(UNIT).history[-1]["note"]


def test_a_running_unit_a_live_process_holds_is_refused_naming_the_holder(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)
    lock_held_by(scene.inst, BRANCH, os.getpid())
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert str(os.getpid()) in out
    assert scene.snapshot() == before
    assert scene.untouched()


def test_a_running_unit_with_a_live_lease_is_refused_naming_the_holder(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)
    assert scene.lease(UNIT, "tab:chat-7")
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "tab:chat-7" in out
    assert scene.snapshot() == before


def test_a_running_unit_with_a_lease_left_by_a_process_that_is_gone_is_retired(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    from agent_build_kit.pipeline.lease import lease_dir

    running(scene)
    leave_lease(lease_dir(scene.inst.state_dir), UNIT)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"


def test_a_dry_run_of_an_idle_running_unit_says_so_and_changes_nothing(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--dry-run")

    assert code == 0
    assert "idle" in out
    assert scene.snapshot() == before


@pytest.mark.parametrize("holder", ["none", "gone", "live"])
def test_the_command_and_the_scheduler_agree_on_which_running_units_are_idle(
    scene: Scene,  # noqa: F811
    capsys,
    holder: str,
) -> None:
    running(scene)
    if holder != "none":
        lock_held_by(scene.inst, BRANCH, os.getpid() if holder == "live" else dead_pid())
    units = scene.store.all()
    idle = cli._idle_units(scene.inst, units, ())
    occupied = cli.slot_occupancy(units, (), (), idle=idle)
    scheduler_says_idle = not any(UNIT in ids for ids in occupied.values())

    code, _ = scene.retire(capsys, UNIT)

    assert scheduler_says_idle == (holder != "live")
    assert (code == 0) == scheduler_says_idle


# The refusals that are not about `running` are as they were.


@pytest.mark.parametrize("state", ["merged", "closed", "satisfied", "retired"])
def test_a_finished_unit_is_still_refused(scene: Scene, capsys, state: str) -> None:  # noqa: F811
    scene.add(UNIT, state, pr=4)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "finished" in out
    assert scene.snapshot() == before


def test_a_started_dependent_stacked_on_an_idle_running_unit_still_refuses(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    running(scene)
    scene.add("feature/4", branch=True, depends_on=(UNIT,))
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "feature/4" in out
    assert scene.snapshot() == before


def test_an_idle_running_unit_with_a_group_nobody_builds_still_needs_a_reason(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, "running", groups=(2,))
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "--reason" in out
    assert scene.snapshot() == before


# The idle test is read before the command's own lock, so what happens between the read and the
# lock is checked again.


def held_then(scene: Scene, monkeypatch: pytest.MonkeyPatch, *answers: bool, between=None) -> None:  # noqa: F811
    """`branch_is_held` as the command reads it: each call gives the next answer, and the first
    also runs `between`, as a run would between the read and the lock."""
    from agent_build_kit.cli import pipeline as pipe

    remaining = list(answers)

    def held(inst, branch) -> bool:
        if between is not None and len(remaining) == len(answers):
            between()
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    monkeypatch.setattr(pipe, "branch_is_held", held)


def test_a_run_that_finished_between_the_read_and_the_lock_is_not_retired_as_idle(
    scene: Scene,  # noqa: F811
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene.add(UNIT, "running", pr=4)
    scene.built_elsewhere(UNIT)
    held_then(
        scene, monkeypatch, False, between=lambda: scene.store.set_state(UNIT, UnitState.IN_REVIEW)
    )

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert UNIT in out and "in_review" in out
    assert scene.unit(UNIT).state == "in_review"
    assert not any("idle" in str(entry.get("note", "")) for entry in scene.unit(UNIT).history)
    assert scene.untouched()


def test_a_holder_that_exits_between_the_read_and_the_lock_leaves_the_unit_idle(
    scene: Scene,  # noqa: F811
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running(scene)
    held_then(scene, monkeypatch, True, False)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert "idle" in scene.unit(UNIT).history[-1]["note"]


def test_a_running_unit_with_no_recorded_branch_is_judged_by_the_branch_it_would_use(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, "running", branch=False)
    scene.built_elsewhere(UNIT)
    lock_held_by(scene.inst, BRANCH, os.getpid())
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert str(os.getpid()) in out
    assert scene.snapshot() == before
