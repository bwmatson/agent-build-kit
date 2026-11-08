"""A restack names a lock file that stops git, and clears one a dead git process left behind.

These run against real repositories and linked worktrees; a lock is made old by setting its
modification time, and whether a git process runs in the worktree is the one seam replaced.
"""

import logging
import os
import time
from pathlib import Path

import pytest

from agent_build_kit.pipeline import restack, shell
from agent_build_kit.pipeline.git_output import GitLockFailed
from agent_build_kit.pipeline.restack import ConflictContext, Moved, move_branch_onto
from tests.factories import commit, git, init_repo

DAY = 24 * 3600


class Tree:
    """A linked worktree on `spec/x/1` with a base commit, the branch's own commit, and a
    newer commit on `main` to move onto."""

    def __init__(self, tmp_path: Path) -> None:
        repo = init_repo(tmp_path / "repo")
        self.old_base = commit(repo, "base.txt", "base\n")
        self.path = tmp_path / "wt"
        git(repo, "worktree", "add", "-q", "-b", "spec/x/1", str(self.path), "main")
        commit(self.path, "own.txt", "own\n")
        self.new_base = commit(repo, "main.txt", "newer\n")
        self.git_dir = Path(git(self.path, "rev-parse", "--absolute-git-dir"))

    def lock(self, name: str = "MERGE_RR.lock", *, age: int = DAY, content: str = "") -> Path:
        path = self.git_dir / name
        path.write_text(content)
        then = time.time() - age
        os.utime(path, (then, then))
        return path

    def move(self) -> Moved:
        return move_branch_onto(
            self.path, "spec/x/1", new_base=self.new_base, old_base=self.old_base
        )

    def try_move(self) -> None:
        """Move, whatever the lock does to it: only the lock's fate is asserted."""
        try:
            self.move()
        except (RuntimeError, OSError):
            pass


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


@pytest.fixture(autouse=True)
def no_git_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell, "git_running_in", lambda worktree: False)


def test_a_commit_that_meets_a_lock_reports_its_path_and_the_command(tree: Tree) -> None:
    lock = tree.lock()
    (tree.path / "own.txt").write_text("changed\n")
    git(tree.path, "add", "own.txt")

    with pytest.raises(GitLockFailed) as raised:
        restack.git(tree.path, "commit", "-q", "--no-verify", "-m", "again")

    assert raised.value.path == str(lock)
    assert "MERGE_RR.lock" in str(raised.value)
    assert "commit" in raised.value.command


def test_a_rebase_stopped_by_a_lock_is_named_and_never_handed_to_the_resolver(
    tree: Tree,
) -> None:
    lock = tree.lock("index.lock", age=60)
    head = git(tree.path, "rev-parse", "spec/x/1")
    asked: list[str] = []

    def resolve(prompt: str, **kwargs: object) -> None:
        asked.append(prompt)

    with pytest.raises(GitLockFailed) as raised:
        move_branch_onto(
            tree.path,
            "spec/x/1",
            new_base=tree.new_base,
            old_base=tree.old_base,
            resolve=resolve,
            context=ConflictContext(
                moving_unit="x/1", moving_intent="a", onto_unit="x/0", onto_intent="b"
            ),
        )

    assert raised.value.path == str(lock)
    assert "rebase" in raised.value.command
    assert asked == []
    assert git(tree.path, "rev-parse", "spec/x/1") == head


def test_an_empty_old_rerere_lock_is_cleared_and_the_log_names_it(
    tree: Tree, caplog: pytest.LogCaptureFixture
) -> None:
    lock = tree.lock()

    with caplog.at_level(logging.INFO):
        moved = tree.move()

    assert not lock.exists()
    assert moved.sha == git(tree.path, "rev-parse", "spec/x/1")
    assert "MERGE_RR.lock" in caplog.text


def test_an_old_empty_index_lock_is_cleared(tree: Tree) -> None:
    lock = tree.lock("index.lock")

    tree.move()

    assert not lock.exists()


@pytest.mark.parametrize(
    ("name", "age", "content"),
    [
        pytest.param("MERGE_RR.lock", 60, "", id="younger-than-the-limit"),
        pytest.param("MERGE_RR.lock", DAY, "held\n", id="non-empty"),
        pytest.param("HEAD.lock", DAY, "", id="another-lock"),
    ],
)
def test_a_lock_that_is_not_clearly_dead_is_left_and_named(
    tree: Tree, caplog: pytest.LogCaptureFixture, name: str, age: int, content: str
) -> None:
    lock = tree.lock(name, age=age, content=content)

    with caplog.at_level(logging.INFO):
        tree.try_move()

    assert lock.exists()
    assert name in caplog.text


def test_no_lock_is_cleared_where_a_git_process_is_running(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lock = tree.lock()
    monkeypatch.setattr(shell, "git_running_in", lambda worktree: True)

    with caplog.at_level(logging.INFO):
        tree.try_move()

    assert lock.exists()
    assert "MERGE_RR.lock" in caplog.text
