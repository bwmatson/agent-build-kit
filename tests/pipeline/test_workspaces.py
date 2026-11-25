"""A worktree and a lock per unit.

Units run in parallel, so each needs its own checkout, and no two runs may
ever work the same branch (docs/architecture.md).

Two rules shape this, both learned from sandcastle's worktree handling:

- **Locks fail fast.** Unlike e2e-test, which is a queue, two runs on one branch
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
    changed_paths,
    operation_in_progress,
    prepare_detached,
    prepare_worktree,
    save_leftovers,
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
    tree = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )

    assert tree.exists()
    assert tree != repo
    assert (tree / "README.md").exists()


def test_the_branch_is_created_on_its_base(repo: Path, tmp_path: Path) -> None:
    git(repo, "checkout", "-q", "-b", "spec/change/1")
    (repo / "parent.txt").write_text("from the parent unit\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "parent work")
    git(repo, "checkout", "-q", "main")

    tree = prepare_worktree(
        repo, "spec/change/2", base="spec/change/1", root=tmp_path / "trees", name=repo.name
    )

    assert (tree / "parent.txt").exists(), "a stacked unit starts from its parent's work"


def test_an_existing_branch_is_reused_with_its_commits(repo: Path, tmp_path: Path) -> None:
    """Deterministic branch names exist so a re-run continues where the last
    one stopped. Recreating the branch would orphan that work."""
    first = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )
    (first / "progress.txt").write_text("half done\n")
    git(first, "add", "-A")
    git(first, "commit", "-qm", "test: half done")

    again = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )

    assert (again / "progress.txt").exists()


def test_a_dirty_worktree_is_reported_not_cleaned(repo: Path, tmp_path: Path) -> None:
    """Uncommitted work may be the only copy of something. Reusing it blindly
    would risk committing it into the wrong unit; wiping it would lose it."""
    tree = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )
    (tree / "scratch.txt").write_text("unsaved\n")

    with pytest.raises(DirtyWorktree):
        prepare_worktree(
            repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
        )

    assert (tree / "scratch.txt").exists(), "the file is still there to rescue"


def test_a_dirty_worktrees_paths_are_exact(repo: Path, tmp_path: Path) -> None:
    tree = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )
    (tree / "a b.txt").write_text("x\n")
    (tree / "dir").mkdir()
    (tree / "dir" / "é.txt").write_text("y\n")

    with pytest.raises(DirtyWorktree) as dirty:
        prepare_worktree(
            repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
        )

    assert sorted(dirty.value.paths) == ["a b.txt", "dir/é.txt"]


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
        tree = prepare_worktree(repo, "spec/change/1", base="main", root=trees, name=repo.name)

        assert locks not in tree.parents
        assert not list(tree.glob("**/*.lock"))


def _head(tree: Path) -> str:
    return git(tree, "rev-parse", "HEAD")


def test_a_detached_checkout_sits_at_its_ref_on_no_branch(repo: Path, tmp_path: Path) -> None:
    # app's dev stack attaches to platform's, which e2e-test brings up from
    # main — not from whatever the user's own checkout has on it.
    tree = prepare_detached(
        repo, "_dev_stack_base", ref="main", root=tmp_path / "trees", name=repo.name
    )

    assert tree == tmp_path / "trees" / repo.name / "_dev_stack_base"
    assert _head(tree) == _head(repo)
    on_branch = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=tree, check=False)
    assert on_branch.returncode != 0


def test_a_detached_checkout_moves_when_its_ref_does(repo: Path, tmp_path: Path) -> None:
    tree = prepare_detached(
        repo, "_dev_stack_base", ref="main", root=tmp_path / "trees", name=repo.name
    )
    (repo / "later.txt").write_text("merged since\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later")

    again = prepare_detached(
        repo, "_dev_stack_base", ref="main", root=tmp_path / "trees", name=repo.name
    )

    assert again == tree
    assert _head(tree) == _head(repo)
    assert (tree / "later.txt").exists()


# --- leftovers: saved to a ref, then only those files cleaned -------------------------------

LOCKS = ("deps.lock",)
ARTIFACTS = ("out/**",)
SAVED = {
    "notes.txt": "edited by hand\n",
    "staged.txt": "new and staged\n",
    "loose/stray.txt": "not added\n",
}


@pytest.fixture
def stray_tree(repo: Path, tmp_path: Path) -> Path:
    """A unit's worktree holding every kind of uncommitted file: three the save takes (a modified
    tracked file, a staged new file, an untracked file in a folder) and three it leaves (an
    ignored file, a tracked lock the sync rewrote, an untracked artifact)."""
    (repo / ".gitignore").write_text("ignored.log\n")
    (repo / "notes.txt").write_text("notes\n")
    (repo / "deps.lock").write_text("locked\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "more")
    tree = prepare_worktree(
        repo, "spec/change/1", base="main", root=tmp_path / "trees", name=repo.name
    )
    for name, text in SAVED.items():
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text(text)
    git(tree, "add", "staged.txt")
    (tree / "ignored.log").write_text("scratch\n")
    (tree / "deps.lock").write_text("re-resolved\n")
    (tree / "out").mkdir()
    (tree / "out" / "build.bin").write_text("artifact\n")
    return tree


def test_saved_leftovers_are_one_commit_on_the_branch_head_under_a_numbered_ref(
    stray_tree: Path,
) -> None:
    head = _head(stray_tree)

    saved = save_leftovers(stray_tree, "change/1", locks=LOCKS, artifacts=ARTIFACTS)

    assert saved.ref == "refs/abk/leftovers/change/1/1"
    assert sorted(saved.files) == sorted(SAVED)
    assert git(stray_tree, "rev-parse", f"{saved.ref}^") == head, "one commit on the head"
    for name, text in SAVED.items():
        assert git(stray_tree, "show", f"{saved.ref}:{name}") == text.rstrip("\n")
    changed = git(stray_tree, "diff", "--name-only", head, saved.ref).splitlines()
    assert sorted(changed) == sorted(SAVED), "the lock, the artifact and the ignored file are out"


def test_a_second_save_for_the_unit_takes_the_next_number_and_leaves_the_first(
    stray_tree: Path,
) -> None:
    first = save_leftovers(stray_tree, "change/1", locks=LOCKS, artifacts=ARTIFACTS)
    first_commit = git(stray_tree, "rev-parse", first.ref)
    (stray_tree / "again.txt").write_text("another\n")

    second = save_leftovers(stray_tree, "change/1", locks=LOCKS, artifacts=ARTIFACTS)

    assert second.ref == "refs/abk/leftovers/change/1/2"
    assert git(stray_tree, "rev-parse", first.ref) == first_commit
    assert second.files == ("again.txt",)


def test_a_staged_rename_is_saved_with_its_source_and_both_are_cleaned(stray_tree: Path) -> None:
    git(stray_tree, "mv", "notes.txt", "moved.txt")

    saved = save_leftovers(stray_tree, "change/1", locks=LOCKS, artifacts=ARTIFACTS)

    in_ref = git(stray_tree, "ls-tree", "-r", "--name-only", saved.ref).splitlines()
    assert "moved.txt" in in_ref
    assert "notes.txt" not in in_ref, "the source is saved as a deletion"
    assert changed_paths(stray_tree, artifacts=ARTIFACTS) == ("deps.lock",), "only the lock is left"
    assert (stray_tree / "notes.txt").read_text() == "notes\n"
    assert not (stray_tree / "moved.txt").exists()


def test_a_revert_stopped_on_a_conflict_is_an_operation_in_progress(repo: Path) -> None:
    for text in ("one\n", "two\n"):
        (repo / "README.md").write_text(text)
        git(repo, "commit", "-qam", text.strip())
    assert not operation_in_progress(repo)

    reverted = subprocess.run(
        ["git", "revert", "--no-edit", "HEAD~1"], cwd=repo, capture_output=True, check=False
    )

    assert reverted.returncode != 0
    assert operation_in_progress(repo)
    git(repo, "revert", "--abort")
    assert not operation_in_progress(repo)


def test_saving_cleans_only_the_saved_files_and_moves_nothing_on_the_branch(
    stray_tree: Path,
) -> None:
    head = _head(stray_tree)
    branches = git(stray_tree, "branch", "--list")

    save_leftovers(stray_tree, "change/1", locks=LOCKS, artifacts=ARTIFACTS)

    assert _head(stray_tree) == head, "no commit on the branch"
    assert git(stray_tree, "branch", "--list") == branches
    assert changed_paths(stray_tree, artifacts=ARTIFACTS) == ("deps.lock",), "only the lock is left"
    assert (stray_tree / "notes.txt").read_text() == "notes\n"
    assert not (stray_tree / "staged.txt").exists()
    assert not (stray_tree / "loose").exists(), "a folder the removal emptied goes too"
    assert (stray_tree / "ignored.log").read_text() == "scratch\n"
    assert (stray_tree / "deps.lock").read_text() == "re-resolved\n"
    assert (stray_tree / "out" / "build.bin").read_text() == "artifact\n"
    assert git(stray_tree, "diff", "--cached", "--name-only") == "", "the index is the head's"
