"""`abk retire` keeps the branch, the worktree and the remote branch unless `--delete-branch`
is given, and counts commits that were never pushed before deleting them (spec:
a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"
BRANCH = f"spec/{UNIT}"


def pushed_unit(scene: Scene, *, unpushed: int = 0) -> None:  # noqa: F811
    """A planned unit with a worktree, one pushed commit and `unpushed` more after it."""
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    scene.commits(UNIT, 1)
    scene.worktree(UNIT)
    scene.push(UNIT)
    if unpushed:
        scene.commits(UNIT, unpushed)


def test_nothing_is_deleted_without_the_flag(scene: Scene, capsys) -> None:  # noqa: F811
    pushed_unit(scene)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert scene.has_branch(UNIT) and scene.has_worktree(UNIT)
    assert scene.host.deleted == []


def test_the_flag_removes_the_worktree_and_both_branches(scene: Scene, capsys) -> None:  # noqa: F811
    pushed_unit(scene)

    code, _ = scene.retire(capsys, UNIT, "--delete-branch")

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert not scene.has_worktree(UNIT) and not scene.has_branch(UNIT)
    assert scene.host.deleted == [BRANCH]


def test_a_branch_that_was_never_pushed_is_not_deleted_on_the_host(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    scene.commits(UNIT, 0)

    code, _ = scene.retire(capsys, UNIT, "--delete-branch")

    assert code == 0
    assert not scene.has_branch(UNIT)
    assert scene.host.deleted == []


def test_a_tree_with_uncommitted_changes_refuses_before_anything_changes(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    pushed_unit(scene)
    (scene.worktree(UNIT) / "half-done.txt").write_text("not committed\n")
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--delete-branch")

    assert code == 1
    assert "uncommitted" in out
    assert scene.snapshot() == before
    assert scene.has_branch(UNIT) and scene.has_worktree(UNIT)
    assert scene.untouched()


def test_commits_after_the_last_pushed_one_refuse_the_deletion_and_are_counted(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    pushed_unit(scene, unpushed=3)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--delete-branch")

    assert code == 1
    assert "3 commits not pushed" in out
    assert scene.snapshot() == before
    assert scene.has_branch(UNIT) and scene.has_worktree(UNIT)
    assert scene.untouched()


def test_discarding_them_deletes_the_branch(scene: Scene, capsys) -> None:  # noqa: F811
    pushed_unit(scene, unpushed=3)

    code, _ = scene.retire(capsys, UNIT, "--delete-branch", "--discard-unpushed")

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert not scene.has_branch(UNIT) and not scene.has_worktree(UNIT)
    assert scene.host.deleted == [BRANCH]


def test_a_branch_never_pushed_counts_its_commits_from_its_base(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)
    scene.commits(UNIT, 2)

    code, out = scene.retire(capsys, UNIT, "--delete-branch")

    assert code == 1
    assert "2 commits not pushed" in out
    assert scene.has_branch(UNIT)


def test_discarding_without_deleting_is_meaningless_and_refused(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    pushed_unit(scene, unpushed=1)
    before = scene.snapshot()

    code, out = scene.retire(capsys, UNIT, "--discard-unpushed")

    assert code == 1
    assert "--delete-branch" in out
    assert scene.snapshot() == before
    assert scene.has_branch(UNIT)
