"""A worktree and a lock per unit.

Units run in parallel, so each needs its own checkout, and no two runs may
ever work the same branch (docs/architecture.md).

Two rules shape this, both learned from sandcastle's worktree handling:

- **Locks fail fast.** Unlike tier 2, which is a queue, two runs on one branch
  means the scheduler handed the same unit out twice. Waiting would hide the
  bug; failing surfaces it.
- **Agent work is never discarded.** A worktree is reused if it exists, and a
  dirty one is reported rather than cleaned — uncommitted work may be the only
  copy of something.
"""

import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    DirtyWorktree,
    branch_lock,
    prepare_detached,
    prepare_worktree,
)
from tests.factories import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def test_a_unit_gets_its_own_checkout(repo: Path, tmp_path: Path) -> None:
    tree = prepare_worktree(repo, "spec/change/1", base="main", root=tmp_path / "trees")

    assert tree.exists()
    assert tree != repo
    assert (tree / "README.md").exists()


def test_the_branch_is_created_on_its_base(repo: Path, tmp_path: Path) -> None:
    git(repo, "checkout", "-q", "-b", "spec/change/1")
    (repo / "parent.txt").write_text("from the parent unit\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "parent work")
    git(repo, "checkout", "-q", "main")

    tree = prepare_worktree(repo, "spec/change/2", base="spec/change/1", root=tmp_path / "trees")

    assert (tree / "parent.txt").exists(), "a stacked unit starts from its parent's work"


def test_an_existing_branch_is_reused_with_its_commits(repo: Path, tmp_path: Path) -> None:
    """Deterministic branch names exist so a re-run continues where the last
    one stopped. Recreating the branch would orphan that work."""
    first = prepare_worktree(repo, "spec/change/1", base="main", root=tmp_path / "trees")
    (first / "progress.txt").write_text("half done\n")
    git(first, "add", "-A")
    git(first, "commit", "-qm", "test: half done")

    again = prepare_worktree(repo, "spec/change/1", base="main", root=tmp_path / "trees")

    assert (again / "progress.txt").exists()


def test_a_dirty_worktree_is_reported_not_cleaned(repo: Path, tmp_path: Path) -> None:
    """Uncommitted work may be the only copy of something. Reusing it blindly
    would risk committing it into the wrong unit; wiping it would lose it."""
    tree = prepare_worktree(repo, "spec/change/1", base="main", root=tmp_path / "trees")
    (tree / "scratch.txt").write_text("unsaved\n")

    with pytest.raises(DirtyWorktree):
        prepare_worktree(repo, "spec/change/1", base="main", root=tmp_path / "trees")

    assert (tree / "scratch.txt").exists(), "the file is still there to rescue"


def test_two_runs_on_one_branch_fail_fast(tmp_path: Path) -> None:
    """Contention here is a scheduler bug: the same unit was handed out twice.
    Waiting would hide that; failing surfaces it."""
    locks = tmp_path / "locks"

    with branch_lock("spec/change/1", root=locks):
        with pytest.raises(BranchBusy):
            with branch_lock("spec/change/1", root=locks):
                pass


def test_different_branches_do_not_contend(tmp_path: Path) -> None:
    locks = tmp_path / "locks"

    with branch_lock("spec/change/1", root=locks):
        with branch_lock("spec/change/2", root=locks):
            pass


def test_the_lock_is_released_when_a_run_fails(tmp_path: Path) -> None:
    locks = tmp_path / "locks"

    with pytest.raises(ValueError):  # noqa: PT012 — the raise is the point
        with branch_lock("spec/change/1", root=locks):
            raise ValueError("boom")

    with branch_lock("spec/change/1", root=locks):
        pass


def test_a_lock_left_by_a_dead_process_is_reclaimed(tmp_path: Path) -> None:
    """A crashed run must not wedge its branch forever. The pid in the file is
    what tells a stale lock from a live one."""
    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "spec_change_1.lock").write_text('{"pid": 999999, "branch": "spec/change/1"}')

    with branch_lock("spec/change/1", root=locks):
        pass


def test_a_lock_held_by_a_living_process_is_respected(tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "spec_change_1.lock").write_text(
        f'{{"pid": {os.getpid()}, "branch": "spec/change/1"}}'
    )

    with pytest.raises(BranchBusy):
        with branch_lock("spec/change/1", root=locks):
            pass


def test_locks_live_outside_the_worktrees(repo: Path, tmp_path: Path) -> None:
    """Anything inside the worktree is visible to the agent, which could
    delete it or commit it by accident."""
    locks = tmp_path / "locks"
    trees = tmp_path / "trees"

    with branch_lock("spec/change/1", root=locks):
        tree = prepare_worktree(repo, "spec/change/1", base="main", root=trees)

        assert locks not in tree.parents
        assert not list(tree.glob("**/*.lock"))


def _head(tree: Path) -> str:
    return git(tree, "rev-parse", "HEAD")


def test_a_detached_checkout_sits_at_its_ref_on_no_branch(repo: Path, tmp_path: Path) -> None:
    # app's dev stack attaches to platform's, which tier 2 brings up from
    # main — not from whatever the user's own checkout has on it.
    tree = prepare_detached(repo, "_dev_stack_base", ref="main", root=tmp_path / "trees")

    assert tree == tmp_path / "trees" / repo.name / "_dev_stack_base"
    assert _head(tree) == _head(repo)
    on_branch = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=tree, check=False)
    assert on_branch.returncode != 0


def test_a_detached_checkout_moves_when_its_ref_does(repo: Path, tmp_path: Path) -> None:
    tree = prepare_detached(repo, "_dev_stack_base", ref="main", root=tmp_path / "trees")
    (repo / "later.txt").write_text("merged since\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later")

    again = prepare_detached(repo, "_dev_stack_base", ref="main", root=tmp_path / "trees")

    assert again == tree
    assert _head(tree) == _head(repo)
    assert (tree / "later.txt").exists()
