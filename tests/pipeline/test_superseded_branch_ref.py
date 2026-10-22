"""A superseded unit's branch is kept under a ref (spec: unit-superseding)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.workspaces import branch_held, branch_lock, keep_superseded_branch
from tests.factories import commit, init_repo

BRANCH = "spec/app/3"
UNIT_ID = "app/3"
REF = f"refs/spec-driven/superseded/{UNIT_ID}"


def repo_with_branch(tmp_path: Path) -> tuple[Path, Path, str]:
    """A repository with the unit's branch one commit past main, and a bare remote holding it."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.txt")
    git(repo, "checkout", "-q", "-b", BRANCH)
    tip = commit(repo, "work.txt")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", BRANCH)
    return repo, remote, tip


def test_the_tip_is_kept_under_the_ref_and_the_lock_is_free_after(tmp_path: Path) -> None:
    repo, _, tip = repo_with_branch(tmp_path)
    locks = tmp_path / "locks"

    kept = keep_superseded_branch(repo, BRANCH, UNIT_ID, lock_root=locks)

    assert kept is True
    assert git_out(repo, "rev-parse", REF).strip() == tip
    assert not branch_held(BRANCH, root=locks)


def test_the_remote_branch_is_untouched(tmp_path: Path) -> None:
    repo, remote, tip = repo_with_branch(tmp_path)

    keep_superseded_branch(repo, BRANCH, UNIT_ID, lock_root=tmp_path / "locks")

    assert git_out(remote, "rev-parse", BRANCH).strip() == tip
    assert git_out(repo, "rev-parse", BRANCH).strip() == tip


def test_a_branch_a_live_process_holds_is_left_alone(tmp_path: Path) -> None:
    repo, _, _ = repo_with_branch(tmp_path)
    locks = tmp_path / "locks"

    with branch_lock(BRANCH, root=locks):
        kept = keep_superseded_branch(repo, BRANCH, UNIT_ID, lock_root=locks)
        still_held = branch_held(BRANCH, root=locks)

    assert kept is False
    assert still_held, "the holder's lock is not taken over or removed"
    assert git(repo, "rev-parse", "--verify", "-q", REF, check=False).returncode != 0
