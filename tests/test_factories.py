"""The helpers in `tests/factories.py` that other tests lean on.

`commit` is the commit helper the restack tests share (spec: dry-cleanup, test helpers defined
once). `who_pushed` is a diagnostic: it must never fail a test it only decorates.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.factories import commit, git, init_repo, who_pushed


def test_commit_writes_the_file_and_commits_it_with_the_name_in_the_message(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")

    sha = commit(repo, "markers.py", "MARKERS = 1\n")

    assert sha == git(repo, "rev-parse", "HEAD")
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


def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    return remote


def push_branch(tmp_path: Path, remote: Path, branch: str) -> str:
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", branch, str(work)], check=True)
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "f").write_text("x")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "one")
    git(work, "push", "-q", str(remote), branch)
    return git(work, "rev-parse", "HEAD").strip()


def test_a_branch_with_a_reflog_shows_it(tmp_path: Path) -> None:
    remote = bare_remote(tmp_path)
    git(remote, "config", "core.logAllRefUpdates", "always")
    sha = push_branch(tmp_path, remote, "feature")

    shown = who_pushed(remote, "feature", ["git push one"])

    reflog = shown.split("--- remote reflog of feature ---")[1].split("--- every `git push`")[0]
    assert sha[:7] in reflog


def test_a_branch_without_a_reflog_does_not_raise(tmp_path: Path) -> None:
    remote = bare_remote(tmp_path)
    push_branch(tmp_path, remote, "feature")

    shown = who_pushed(remote, "feature", [])

    assert "remote reflog of feature" in shown


def test_a_missing_branch_does_not_raise(tmp_path: Path) -> None:
    shown = who_pushed(bare_remote(tmp_path), "feature", [])

    assert "remote reflog of feature" in shown
