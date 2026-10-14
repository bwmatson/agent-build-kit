"""The commit helper the restack tests share (spec: dry-cleanup, test helpers defined once)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import commit, git, init_repo


def test_commit_writes_the_file_and_commits_it_with_the_name_in_the_message(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")

    commit(repo, "markers.py", "MARKERS = 1\n")

    assert (repo / "markers.py").read_text() == "MARKERS = 1\n"
    assert git(repo, "log", "-1", "--format=%s") == "write markers.py"
    assert git(repo, "status", "--porcelain") == ""


def test_commit_content_defaults_to_a_single_character(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    commit(repo, "a.txt")

    assert (repo / "a.txt").read_text() == "x"


def test_commit_stages_everything_so_a_caller_can_commit_over_earlier_changes(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "a.txt")
    (repo / "stray.txt").write_text("left over")

    commit(repo, "b.txt", "second")

    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["b.txt", "stray.txt"]
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
