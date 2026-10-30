"""`abk retire --dry-run` prints every step, changes and calls nothing, and exits as the real
command would; a real run records who did it and why (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import os

import pytest

from tests.branch_lock_fakes import lock_held_by
from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"
BRANCH = f"spec/{UNIT}"


def everything_to_do(scene: Scene) -> None:  # noqa: F811
    """A unit in review with a pull request, a worktree, a pushed commit and three more, a
    group nobody else builds, and a planned unit waiting on it."""
    scene.add(UNIT, "in_review", pr=4, groups=(2,))
    scene.commits(UNIT, 1)
    scene.worktree(UNIT)
    scene.push(UNIT)
    scene.commits(UNIT, 3)
    scene.add("feature/4", branch=False, depends_on=(UNIT,))
    scene.record("feature")


def test_a_dry_run_prints_every_step_and_changes_nothing(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    everything_to_do(scene)
    before = scene.snapshot()
    flags = ("--dry-run", "--delete-branch", "--discard-unpushed", "--reason", "narrowed")

    code, out = scene.retire(capsys, UNIT, *flags)

    assert code == 0
    assert "retired" in out
    assert any("group 2" in line and "released" in line for line in out.splitlines())
    assert any("feature/4" in line and "planned" in line for line in out.splitlines())
    assert "#4" in out
    assert "worktree" in out and BRANCH in out
    assert "3 commits not pushed" in out
    assert scene.snapshot() == before
    assert scene.untouched() and scene.host.calls == []
    assert scene.has_branch(UNIT) and scene.has_worktree(UNIT)


def test_a_dry_run_exits_as_the_real_command_would_for_unpushed_commits(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    everything_to_do(scene)

    code, out = scene.retire(capsys, UNIT, "--dry-run", "--delete-branch", "--reason", "x")

    assert code == 1
    assert "3 commits not pushed" in out


@pytest.mark.parametrize(
    "state",
    ["merged", "planned"],
    ids=["finished", "group nobody builds, no reason"],
)
def test_a_dry_run_exits_1_for_each_refusal(
    scene: Scene,  # noqa: F811
    capsys,
    state: str,
) -> None:
    scene.add(UNIT, state, groups=(2,))
    before = scene.snapshot()

    code, _ = scene.retire(capsys, UNIT, "--dry-run")

    assert code == 1
    assert scene.snapshot() == before


def test_a_dry_run_exits_1_for_a_running_unit_a_live_process_holds(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT, "running", groups=(2,))
    lock_held_by(scene.inst, BRANCH, os.getpid())
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--dry-run", "--reason", "x")

    assert code == 1
    assert str(os.getpid()) in out
    assert scene.snapshot() == before


def test_a_dry_run_exits_0_where_the_real_command_would_retire(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    before = scene.snapshot()

    code, _ = scene.retire(capsys, UNIT, "--dry-run")

    assert code == 0
    assert scene.snapshot() == before
    assert scene.unit(UNIT).state == "planned"


def test_a_real_run_records_the_state_cause_reason_and_the_command(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)

    code, _ = scene.retire(capsys, UNIT, "--reason", "built in feature/9")

    assert code == 0
    entry = scene.unit(UNIT).history[-1]
    assert entry["state"] == "retired"
    assert entry["cause"] == "retired"
    assert entry["note"] == "built in feature/9"
    assert entry["by"] == "abk retire"
    assert set(entry) == {"state", "at", "note", "cause", "by"}, "no person's name"
