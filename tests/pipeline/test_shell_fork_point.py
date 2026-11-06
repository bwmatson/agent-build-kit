"""`fork_point` says where a branch left a ref, in one place (spec: unit-own-tests): the commit
the two last shared, or an empty string, never an exception, when git cannot say."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.shell import fork_point
from tests.factories import commit, git, init_repo


def test_a_branch_that_left_a_ref_that_has_moved_on_answers_where_it_left(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    left = commit(repo, "base.txt")
    git(repo, "switch", "-q", "-c", "unit")
    commit(repo, "unit.txt")
    git(repo, "switch", "-q", "main")
    commit(repo, "moved.txt")
    git(repo, "switch", "-q", "unit")

    assert fork_point(repo, "main") == left


def test_a_branch_at_the_ref_answers_the_refs_own_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    tip = commit(repo, "base.txt")
    git(repo, "switch", "-q", "-c", "unit")

    assert fork_point(repo, "main") == tip


def test_a_ref_that_does_not_exist_answers_an_empty_string(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.txt")

    assert fork_point(repo, "no-such-ref") == ""


def test_a_branch_with_no_common_history_answers_an_empty_string(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.txt")
    git(repo, "switch", "-q", "--orphan", "unrelated")
    commit(repo, "other.txt")

    assert fork_point(repo, "main") == ""


def test_a_head_that_is_not_checked_out_is_the_branch_asked_about(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    left = commit(repo, "base.txt")
    git(repo, "switch", "-q", "-c", "unit")
    commit(repo, "unit.txt")
    git(repo, "switch", "-q", "main")
    commit(repo, "moved.txt")

    assert fork_point(repo, "main", "unit") == left
    assert fork_point(repo, "main", "no-such-branch") == ""
