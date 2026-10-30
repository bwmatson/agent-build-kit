"""`abk retire` refuses what it cannot end, before it changes anything (spec:
a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import os

import pytest

from agent_build_kit.pipeline.lease import lease_dir
from tests.attach_driver import leave_lease
from tests.branch_lock_fakes import dead_pid, lock_held_by
from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"


def test_an_unknown_unit_exits_2_and_changes_nothing(scene: Scene, capsys) -> None:  # noqa: F811
    scene.add(UNIT)
    before = scene.snapshot()

    code, out = scene.retire(capsys, "feature/77")

    assert code == 2
    assert "feature/77" in out
    assert scene.snapshot() == before


@pytest.mark.parametrize("state", ["merged", "closed", "satisfied", "retired"])
def test_a_finished_unit_is_refused(scene: Scene, capsys, state: str) -> None:  # noqa: F811
    scene.add(UNIT, state, pr=4)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert UNIT in out and "finished" in out
    assert scene.snapshot() == before
    assert scene.untouched()


def test_a_running_unit_a_live_process_holds_is_refused(scene: Scene, capsys) -> None:  # noqa: F811
    scene.add(UNIT, "running")
    lock_held_by(scene.inst, f"spec/{UNIT}", os.getpid())
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--reason", "x")

    assert code == 1
    assert str(os.getpid()) in out
    assert scene.snapshot() == before


def test_a_branch_lock_held_by_a_live_process_refuses_and_names_it(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    lock_held_by(scene.inst, f"spec/{UNIT}", os.getpid())
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert str(os.getpid()) in out
    assert scene.snapshot() == before


def test_a_live_lease_refuses_and_names_the_holder(scene: Scene, capsys) -> None:  # noqa: F811
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    assert scene.lease(UNIT, "tab:chat-7")
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "tab:chat-7" in out
    assert scene.snapshot() == before


def test_a_started_dependent_stacked_on_it_refuses_and_is_named(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.add("feature/4", branch=True, depends_on=(UNIT,))
    scene.built_elsewhere(UNIT)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT)

    assert code == 1
    assert "feature/4" in out
    assert scene.snapshot() == before


def test_a_lock_left_by_a_process_that_is_gone_does_not_refuse(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    lock_held_by(scene.inst, f"spec/{UNIT}", dead_pid())

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"


def test_a_lease_left_by_a_process_that_is_gone_does_not_refuse(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    leave_lease(lease_dir(scene.inst.state_dir), UNIT)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
