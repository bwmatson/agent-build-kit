"""A restack keeps the changelog's form when the union merge joins two bullets.

`CHANGELOG.md merge=union` keeps a blank line that both branches added only once, so two
branches that each add a bullet at the same place come out with the bullets back to back.
These tests run against real git repositories with that attribute set.
"""

from pathlib import Path

from agent_build_kit.changelog_form import changelog_problems
from agent_build_kit.pipeline.restack import move_branch_onto
from tests.factories import git, init_repo

BASE = """\
# Changelog

## Unreleased

- Base thing.

## 0.1.0 — 2026-09-28

- First release.
"""
TOP = "## Unreleased\n\n"
END = "- Base thing.\n\n"


def _write_and_commit(repo: Path, text: str, message: str) -> None:
    (repo / "CHANGELOG.md").write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def _union_repo(path: Path) -> tuple[Path, str]:
    """A repo with a union-merged changelog on `main`; the repo and that first commit."""
    repo = init_repo(path)
    (repo / ".gitattributes").write_text("CHANGELOG.md merge=union\n")
    _write_and_commit(repo, BASE, "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def _commits_the_move_adds(repo: Path, old_main: str, a_text: str, b_text: str) -> int:
    """Land `spec/a/1` on main, make `spec/b/1` from the old main, move it onto main;
    how many commits the move added to `spec/b/1`."""
    git(repo, "checkout", "-q", "-b", "spec/a/1")
    _write_and_commit(repo, a_text, "a")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "spec/a/1")
    git(repo, "checkout", "-q", "-b", "spec/b/1", old_main)
    _write_and_commit(repo, b_text, "b")
    git(repo, "checkout", "-q", "main")
    own = int(git(repo, "rev-list", "--count", f"{old_main}..spec/b/1").strip())

    move_branch_onto(repo, "spec/b/1", new_base="main", old_base=old_main)

    assert changelog_problems(git(repo, "show", "spec/b/1:CHANGELOG.md")) == []
    return int(git(repo, "rev-list", "--count", "main..spec/b/1").strip()) - own


def test_bullets_the_union_merge_joined_are_separated_in_a_commit_of_their_own(
    tmp_path: Path,
) -> None:
    joined, joined_main = _union_repo(tmp_path / "joined")
    apart, apart_main = _union_repo(tmp_path / "apart")

    added = _commits_the_move_adds(
        joined,
        joined_main,
        BASE.replace(TOP, f"{TOP}- A thing.\n\n"),
        BASE.replace(TOP, f"{TOP}- B thing.\n\n"),
    )
    added_when_apart = _commits_the_move_adds(
        apart,
        apart_main,
        BASE.replace(TOP, f"{TOP}- A thing.\n\n"),
        BASE.replace(END, f"{END}- B thing.\n\n"),
    )

    moved = git(joined, "show", "spec/b/1:CHANGELOG.md")
    assert "- A thing." in moved
    assert "- B thing." in moved
    assert added == 1
    assert git(joined, "show", "--name-only", "--format=", "spec/b/1").split() == ["CHANGELOG.md"]
    assert added_when_apart == 0
