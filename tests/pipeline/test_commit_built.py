"""`commit_built` makes an empty commit that records a group as already built: the message,
then the trailer block with `Already-built: yes` last (spec: built-group-recorded-as-empty-pair).
Real git in a temporary repository.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent_build_kit.pipeline.wiring import CommitRejected, build_commit_built
from tests.factories import git, init_repo

MESSAGE = (
    "feat: Register the marker\n\nThe implementation of this task group.\n\nThe four tests pass."
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def trailer(work: Path, key: str) -> str:
    return git(work, "log", "-1", f"--format=%(trailers:key={key},valueonly)").strip()


def hook(work: Path, body: str) -> None:
    path = work / ".git" / "hooks" / "pre-commit"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_the_commit_holds_no_file_and_carries_the_message(repo: Path) -> None:
    made = build_commit_built(unit_id="feature/1")(MESSAGE, cwd=repo)

    assert made == 1
    assert git(repo, "show", "--name-only", "--format=", "HEAD") == ""
    assert git(repo, "log", "-1", "--format=%s") == "feat: Register the marker"
    body = git(repo, "log", "-1", "--format=%b")
    assert "The implementation of this task group." in body
    assert "The four tests pass." in body


def test_the_unit_and_the_mark_are_the_last_paragraph(repo: Path) -> None:
    build_commit_built(unit_id="feature/1")(MESSAGE, cwd=repo)

    assert trailer(repo, "Unit") == "feature/1"
    assert trailer(repo, "Already-built") == "yes"
    assert trailer(repo, "Adopted-From") == ""
    last = git(repo, "log", "-1", "--format=%B").strip().split("\n\n")[-1]
    assert last.splitlines() == ["Unit: feature/1", "Already-built: yes"]


def test_a_chat_session_adopted_from_is_added_when_set(repo: Path) -> None:
    build_commit_built(unit_id="feature/1", adopted_from="session-7")(MESSAGE, cwd=repo)

    assert trailer(repo, "Adopted-From") == "session-7"
    last = git(repo, "log", "-1", "--format=%B").strip().split("\n\n")[-1]
    assert last.splitlines()[-1] == "Already-built: yes"


def test_the_hooks_run(repo: Path, tmp_path: Path) -> None:
    called = tmp_path / "hook-called"
    hook(repo, f"touch {called}")

    build_commit_built(unit_id="feature/1")(MESSAGE, cwd=repo)

    assert called.exists()


def test_a_hook_that_rejects_raises_commit_rejected_and_makes_no_commit(repo: Path) -> None:
    before = git(repo, "rev-parse", "HEAD")
    hook(repo, "echo 'no empty commits here'; exit 1")

    with pytest.raises(CommitRejected, match="no empty commits here"):
        build_commit_built(unit_id="feature/1")(MESSAGE, cwd=repo)

    assert git(repo, "rev-parse", "HEAD") == before
