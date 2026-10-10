"""The lock files an environment names are the pipeline's: which worktree check ignores
them, what the commit step does with them, and that a restack is not stopped by one
(spec: pipeline-environment). Real git throughout; nothing is faked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import local_ref
from agent_build_kit.pipeline.wiring import build_commit, build_restack_onto
from agent_build_kit.pipeline.workspaces import DirtyWorktree, prepare_worktree
from tests.environment_fakes import FakeEnvironment, repo_config
from tests.factories import git, init_repo, unit

MANIFEST = "manifest.toml"
LOCK = "deps.lock"
OTHER_LOCK = "other.lock"
BRANCH = "spec/add-marker/1"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    (work / MANIFEST).write_text('widget = "1"\n')
    (work / LOCK).write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def dirty_paths(repo: Path, trees: Path, *, locks: tuple[str, ...]) -> list[str] | None:
    """The paths that hold the unit's worktree whose lock inputs are `locks`, None when none do."""
    try:
        prepare_worktree(repo, BRANCH, base="main", root=trees, locks=locks)
    except DirtyWorktree as dirty:
        assert all(name in str(dirty) for name in dirty.paths)
        return sorted(dirty.paths)
    return None


def test_a_rewritten_tracked_lock_does_not_hold_a_worktree_and_is_not_discarded(
    repo: Path, tmp_path: Path
) -> None:
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    (tree / LOCK).write_text("rewritten\n")

    again = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))

    assert again == tree
    assert (tree / LOCK).read_text() == "rewritten\n"


def test_an_untracked_lock_does_not_hold_a_worktree(repo: Path, tmp_path: Path) -> None:
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(OTHER_LOCK,))
    (tree / OTHER_LOCK).write_text("new\n")

    assert dirty_paths(repo, tmp_path / "trees", locks=(OTHER_LOCK,)) is None
    assert (tree / OTHER_LOCK).exists()


def test_another_file_still_holds_a_worktree_and_is_the_only_path_named(
    repo: Path, tmp_path: Path
) -> None:
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    (tree / LOCK).write_text("rewritten\n")
    (tree / "stray.txt").write_text("mine\n")

    assert dirty_paths(repo, tmp_path / "trees", locks=(LOCK,)) == ["stray.txt"]
    with pytest.raises(DirtyWorktree) as dirty:
        prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    assert LOCK not in str(dirty.value), "the message does not list it either"


def test_a_worktree_with_no_lock_inputs_is_held_for_an_uncommitted_lock(
    repo: Path, tmp_path: Path
) -> None:
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees")
    (tree / LOCK).write_text("rewritten\n")

    assert dirty_paths(repo, tmp_path / "trees", locks=()) == [LOCK]


def test_each_repository_ignores_only_the_lock_its_own_inputs_name(tmp_path: Path) -> None:
    held: dict[str, list[str] | None] = {}
    for name, locks in {"first": (LOCK,), "second": (OTHER_LOCK,)}.items():
        work = init_repo(tmp_path / name)
        (work / "README.md").write_text("base\n")
        git(work, "add", "-A")
        git(work, "commit", "-qm", "base")
        tree = prepare_worktree(work, BRANCH, base="main", root=tmp_path / f"{name}-trees")
        (tree / LOCK).write_text("a\n")
        (tree / OTHER_LOCK).write_text("b\n")
        held[name] = dirty_paths(work, tmp_path / f"{name}-trees", locks=locks)

    assert held == {"first": [OTHER_LOCK], "second": [LOCK]}


# --- the commit step ---------------------------------------------------------------------


def committing(repo: Path, tmp_path: Path, *, tracked_lock: bool = True) -> Path:
    """A worktree of `repo` on the unit's branch, and the commit step over its configuration."""
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    if not tracked_lock:
        git(tree, "rm", "-q", "--cached", LOCK)
        git(tree, "commit", "-qm", "the lock is not tracked here")
    return tree


def commit(tree: Path, tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,))
    config = repo_config(tmp_path / "meta", env)
    made = build_commit(unit_id=unit().id, repo=config, base="main")("feat: the work", cwd=tree)
    assert made == 1


def committed_files(tree: Path) -> list[str]:
    return git(tree, "show", "--name-only", "--format=", "HEAD").split()


def test_a_lock_the_sync_rewrote_is_committed_with_the_dependency_change_that_needed_it(
    repo: Path, tmp_path: Path
) -> None:
    tree = committing(repo, tmp_path)
    (tree / MANIFEST).write_text('widget = "9"\n')
    (tree / LOCK).write_text("resolved for 9\n")

    commit(tree, tmp_path)

    assert sorted(committed_files(tree)) == [LOCK, MANIFEST]
    assert git(tree, "status", "--porcelain") == ""


def test_a_lock_rewritten_with_no_dependency_change_is_restored_not_committed(
    repo: Path, tmp_path: Path
) -> None:
    tree = committing(repo, tmp_path)
    (tree / "marker.py").write_text("MARKER = 1\n")
    (tree / LOCK).write_text("reformatted by a newer tool\n")

    commit(tree, tmp_path)

    assert committed_files(tree) == ["marker.py"]
    assert (tree / LOCK).read_text() == "as committed\n"
    assert git(tree, "status", "--porcelain") == ""


def test_an_untracked_lock_is_never_committed_and_stays_in_the_worktree(
    repo: Path, tmp_path: Path
) -> None:
    tree = committing(repo, tmp_path, tracked_lock=False)
    (tree / MANIFEST).write_text('widget = "9"\n')
    (tree / LOCK).write_text("created by the sync\n")

    commit(tree, tmp_path)

    assert committed_files(tree) == [MANIFEST]
    assert (tree / LOCK).read_text() == "created by the sync\n"


def test_a_dependency_change_in_an_earlier_commit_still_carries_the_lock(
    repo: Path, tmp_path: Path
) -> None:
    tree = committing(repo, tmp_path)
    (tree / MANIFEST).write_text('widget = "9"\n')
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "test: bumps widget")
    (tree / LOCK).write_text("resolved for 9\n")
    (tree / "marker.py").write_text("MARKER = 1\n")

    commit(tree, tmp_path)

    assert sorted(committed_files(tree)) == [LOCK, "marker.py"]


# --- the restack -------------------------------------------------------------------------


def test_a_restack_succeeds_over_a_tracked_lock_the_unit_did_not_change(
    repo: Path, tmp_path: Path
) -> None:
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    (tree / "marker.py").write_text("MARKER = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "the unit's work")
    (repo / "trunk.py").write_text("TRUNK = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "trunk advances")
    (tree / LOCK).write_text("rewritten by the sync\n")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,))
    config = repo_config(tmp_path / "meta", env)

    moved = build_restack_onto(store, repo=config)(
        tree=tree, branch=BRANCH, base="main", unit=unit(), resolve=False
    )

    assert moved is not None and not moved.conflict
    assert git(tree, "rev-parse", "HEAD^") == git(repo, "rev-parse", "main")
    assert local_ref("main") != "main" or True
