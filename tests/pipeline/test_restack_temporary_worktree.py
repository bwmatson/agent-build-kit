"""A branch with no worktree is restacked in a temporary one, on no branch.

The stack move handler used to rebase in the repository's own checkout when the
unit had no worktree, switching the operator's checkout to the branch, or being
refused by git when another worktree had it. Here the repository's checkout is
the operator's: it is left on its branch with its working tree as it was.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.restack_turn_fakes import (
    BRANCH,
    OLD_BASE,
    Rig,
    around_the_resolver,
    extra_commit,
    keeps_both,
    mark_resolver,
    rebase_in_progress,
    run_bounded,
    sh,
    spy_git,
)


def checkout_state(repo: Path) -> tuple[str, str, str, str]:
    """The branch, head, status and notes file of the operator's checkout."""
    return (
        sh(repo, "branch", "--show-current"),
        sh(repo, "rev-parse", "HEAD"),
        sh(repo, "status", "--porcelain"),
        (repo / "notes.md").read_text(),
    )


def worktrees(repo: Path) -> int:
    return sh(repo, "worktree", "list", "--porcelain").count("worktree ")


def test_a_branch_with_no_worktree_is_moved_in_a_temporary_one_and_the_checkout_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    (rig.repo / "notes.md").write_text("the operator's edit\n")
    (rig.repo / "scratch.txt").write_text("untracked\n")
    before = checkout_state(rig.repo)
    old_head = sh(rig.repo, "rev-parse", BRANCH)
    seen: list[tuple[Path, str]] = []

    def resolver(request) -> None:
        seen.append((request.cwd, sh(request.cwd, "branch", "--show-current")))
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    assert seen == [(rig.temporary_tree(), "")], "the rebase ran on a detached head"
    assert checkout_state(rig.repo) == before
    assert sh(rig.repo, "rev-parse", BRANCH) != old_head
    sh(rig.repo, "merge-base", "--is-ancestor", "main", BRANCH)
    assert not rig.temporary_tree().exists()
    assert worktrees(rig.repo) == 1


def test_the_temporary_worktree_and_the_branch_move_are_made_inside_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    old_head = sh(rig.repo, "rev-parse", BRANCH)
    calls = spy_git(monkeypatch, rig.lock)

    def resolver(request) -> None:
        mark_resolver(calls, rig.lock, request.cwd)
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    before, during, after = around_the_resolver(calls)
    assert not during.held
    added = [c for c in before if c.verb[:2] == ("worktree", "add")]
    assert added and all(c.held for c in added)
    updates = [c for c in after if c.verb[0] == "update-ref"]
    assert len(updates) == 1 and updates[0].held
    assert updates[0].verb[1] == f"refs/heads/{BRANCH}"
    assert updates[0].verb[-1] == old_head, "a compare-and-swap against the head it started from"
    removed = [c for c in after if c.verb[:2] == ("worktree", "remove")]
    assert removed and all(c.held for c in removed)


def test_a_branch_checked_out_elsewhere_does_not_stop_the_rebase_and_is_not_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    sh(rig.repo, "checkout", "-q", BRANCH)
    old_head = sh(rig.repo, "rev-parse", BRANCH)

    run_bounded(rig.restack)

    stored = rig.store.get(rig.child.id)
    assert sh(rig.repo, "rev-parse", BRANCH) == old_head, "the reference is not moved"
    assert sh(rig.repo, "branch", "--show-current") == BRANCH
    assert stored.state == PLANNED
    assert stored.cause == Cause.RESTACK_DEFERRED
    assert str(rig.repo) in stored.note, "the note names the checkout"
    assert not rig.temporary_tree().exists()
    assert not rebase_in_progress(rig.repo)


def test_a_temporary_worktree_left_by_a_stopped_restack_is_cleared_under_the_turn_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    left = rig.temporary_tree()
    left.parent.mkdir(parents=True, exist_ok=True)
    sh(rig.repo, "worktree", "add", "-q", "--detach", str(left), BRANCH)
    stopped = subprocess.run(
        ["git", "rebase", "--onto", "main", OLD_BASE], cwd=left, capture_output=True, text=True
    )
    assert stopped.returncode != 0 and rebase_in_progress(left), "the leftover is mid-rebase"
    calls = spy_git(monkeypatch, rig.lock)
    trees: list[int] = []

    def resolver(request) -> None:
        mark_resolver(calls, rig.lock, request.cwd)
        trees.append(worktrees(rig.repo))
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    before, _, _ = around_the_resolver(calls)
    cleared = [c for c in before if c.verb[:2] in {("rebase", "--abort"), ("worktree", "remove")}]
    assert cleared and all(c.held for c in cleared)
    assert trees == [2], "the repository's checkout and one temporary tree, not two"
    assert not left.exists()


def test_a_temporary_worktree_left_under_an_earlier_folder_is_cleared_and_the_move_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    left = rig.installation.worktree_root / "worktree" / rig.temporary_tree().name
    left.parent.mkdir(parents=True)
    sh(rig.repo, "worktree", "add", "-q", "--detach", str(left), BRANCH)
    stopped = subprocess.run(
        ["git", "rebase", "--onto", "main", OLD_BASE], cwd=left, capture_output=True, text=True
    )
    assert stopped.returncode != 0 and rebase_in_progress(left), "the leftover is mid-rebase"
    old_head = sh(rig.repo, "rev-parse", BRANCH)

    run_bounded(rig.restack)

    assert sh(rig.repo, "rev-parse", BRANCH) != old_head
    sh(rig.repo, "merge-base", "--is-ancestor", "main", BRANCH)
    assert not left.exists()
    assert "restack-" not in sh(rig.repo, "worktree", "list", "--porcelain")


def test_a_temporary_root_without_the_repos_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="temporary_name"):
        restack.resolved_move(
            rig.repo,
            BRANCH,
            new_base="main",
            old_base=OLD_BASE,
            moving_unit="c/2",
            moving_intent="moving",
            onto_unit="c/1",
            onto_intent="onto",
            temporary_root=rig.installation.worktree_root,
        )


def test_the_checks_of_a_branch_with_no_worktree_run_on_a_checkout_at_the_moved_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    rig.use_clean_approved_branch()
    (rig.repo / "notes.md").write_text("the operator's edit\n")
    seen: list[tuple[Path, str]] = []
    pushed: list[str] = []

    def unit_test(**kwargs: Any):
        def run(*, cwd: Path, base: str, moved_from: str | None = None) -> tuple[bool, str]:
            seen.append((cwd, sh(cwd, "rev-parse", "HEAD")))
            return True, ""

        return run

    monkeypatch.setattr(cli, "build_unit_test", unit_test)
    monkeypatch.setattr(
        cli,
        "push_with_lease",
        lambda repo, branch, *, last_pushed: pushed.append(branch) or sh(repo, "rev-parse", branch),
    )

    run_bounded(rig.restack)

    ((cwd, head),) = seen
    assert cwd != rig.repo
    assert head == sh(rig.repo, "rev-parse", rig.branch), "the checks ran on the moved head"
    assert sh(rig.repo, "merge-base", "main", rig.branch) == sh(rig.repo, "rev-parse", "main")
    assert not cwd.exists() and not rig.temporary_tree().exists()
    assert pushed == [rig.branch]


def test_a_branch_moved_between_making_the_tree_and_the_rebase_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    moved_to = extra_commit(rig.repo, BRANCH, "other.py", tmp_path / "scratch")
    made = []
    real = restack.prepare_detached

    def moves_the_branch_once_the_tree_exists(*args: Any, **kwargs: Any) -> Path:
        path = real(*args, **kwargs)
        if not made:
            sh(rig.repo, "update-ref", f"refs/heads/{BRANCH}", moved_to)
        made.append(path)
        return path

    monkeypatch.setattr(restack, "prepare_detached", moves_the_branch_once_the_tree_exists)

    run_bounded(rig.restack)

    assert len(made) == 2, "started again for the moved branch"
    assert sh(rig.repo, "show", f"{BRANCH}:other.py") == "other.py", "the other writer's commit"
    sh(rig.repo, "merge-base", "--is-ancestor", "main", BRANCH)


def test_the_temporary_tree_is_named_for_the_repo_not_its_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    root = rig.installation.worktree_root

    tree = restack.temporary_tree(rig.repo, BRANCH, root=root, name="lib")

    assert tree == root / "lib" / "restack-spec_c_2"
