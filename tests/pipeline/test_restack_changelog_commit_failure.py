"""A changelog separation whose commit fails cannot fail a finished move.

The separation is a cosmetic commit made after the rebase. Its exit status says the command
failed, not whether the commit landed, so the step looks at what the failed commit did: a
commit that landed is done, and one that did not has its file restored. These run against
real repositories with the union-merge attribute set; the commit is made to fail by a lock
left in the git directory (git exits 128 after the commit landed) or by a hook (nothing lands).
"""

import logging
import stat
from pathlib import Path

import pytest

from agent_build_kit.changelog_form import changelog_problems
from agent_build_kit.pipeline.restack import CHANGELOG_SEPARATED, move_branch_onto
from tests.factories import git, init_repo

BASE = """\
# Changelog

## Unreleased

- Base thing.

## 0.1.0 — 2026-09-28

- First release.
"""
TOP = "## Unreleased\n\n"
A_AT_TOP = BASE.replace(TOP, f"{TOP}- A thing.\n\n")
B_AT_TOP = BASE.replace(TOP, f"{TOP}- B thing.\n\n")


def _write_and_commit(repo: Path, text: str, message: str) -> None:
    (repo / "CHANGELOG.md").write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


@pytest.fixture
def joined(tmp_path: Path) -> tuple[Path, str]:
    """A repo where `main` has moved on with a bullet at the spot `spec/b/1` also added one, so
    moving it joins the two bullets; the repo and the old base."""
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitattributes").write_text("CHANGELOG.md merge=union\n")
    _write_and_commit(repo, BASE, "base")
    old_main = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "-b", "spec/a/1")
    _write_and_commit(repo, A_AT_TOP, "a")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "spec/a/1")
    git(repo, "checkout", "-q", "-b", "spec/b/1", old_main)
    _write_and_commit(repo, B_AT_TOP, "b")
    git(repo, "checkout", "-q", "main")
    return repo, old_main


def _move(repo: Path, old_main: str) -> int:
    """Move `spec/b/1` onto main; how many commits the move added to it."""
    own = int(git(repo, "rev-list", "--count", f"{old_main}..spec/b/1").strip())
    move_branch_onto(repo, "spec/b/1", new_base="main", old_base=old_main)
    return int(git(repo, "rev-list", "--count", "main..spec/b/1").strip()) - own


def test_a_separation_commit_that_failed_after_landing_is_done(joined: tuple[Path, str]) -> None:
    repo, old_main = joined
    # A young lock, so the start of the turn leaves it: the commit lands, then git exits 128.
    lock = repo / git(repo, "rev-parse", "--git-path", "MERGE_RR.lock").strip()
    lock.write_text("")

    added = _move(repo, old_main)

    assert added == 1
    assert git(repo, "log", "-1", "--format=%s", "spec/b/1").strip() == CHANGELOG_SEPARATED
    assert changelog_problems(git(repo, "show", "spec/b/1:CHANGELOG.md")) == []
    assert git(repo, "status", "--porcelain").strip() == ""


def test_a_separation_commit_that_landed_nothing_restores_the_file_and_the_move_finishes(
    joined: tuple[Path, str], caplog: pytest.LogCaptureFixture
) -> None:
    repo, old_main = joined
    hook = repo / git(repo, "rev-parse", "--git-path", "hooks/prepare-commit-msg").strip()
    hook.parent.mkdir(parents=True, exist_ok=True)
    # Refuses only the separation commit, not the rebase's own picks.
    hook.write_text(
        f'#!/bin/sh\ngrep -q "{CHANGELOG_SEPARATED}" "$1" || exit 0\necho refused >&2\nexit 1\n'
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    with caplog.at_level(logging.INFO):
        added = _move(repo, old_main)

    left = git(repo, "show", "spec/b/1:CHANGELOG.md")
    assert added == 0
    assert git(repo, "status", "--porcelain").strip() == ""
    assert (repo / "CHANGELOG.md").read_text().strip() == left.strip()
    assert "- A thing.\n- B thing." in left or "- B thing.\n- A thing." in left
    assert "separat" in caplog.text.lower()
    assert "refused" in caplog.text
