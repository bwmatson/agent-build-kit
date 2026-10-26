"""What the tests of `prepare` moving a branch with no commits share: a real worktree on an old
base, the base advanced underneath it, and the runner callables that read the real repository.

The branch is a real git repository, which the runner's worktree is; the agent is the builder and
reviewer fakes of the graph tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.wiring import branch_commits, build_move_empty_branch, tip
from tests.factories import commit, git
from tests.graph.test_outside_commits_prompt import branch, drive
from tests.runner_fakes import Recorder

BRANCH = "spec/add-marker/1"
MOVED = "moved the empty branch from "


def empty_branch(tmp_path: Path) -> tuple[Recorder, dict[str, Any], Path]:
    """A worktree on `main` with the unit's branch at its tip and no commit of its own, and
    the callables that count and move it with the real git."""
    repo = branch(tmp_path)
    recorder, _, overrides = drive(tmp_path)
    real = {
        **overrides,
        "branch_commits": branch_commits,
        "base_tip": tip,
        "move_empty_branch": build_move_empty_branch(),
    }
    return recorder, real, repo


def advance(repo: Path, name: str = "upstream.txt", on: str = "main", ref: str = "") -> str:
    """Add a commit to `on` and make it what the remote's trunk (`ref`, by default `on`'s
    remote) names, leaving the unit's branch checked out where it was; the new tip."""
    git(repo, "checkout", "-q", on)
    new = commit(repo, name)
    git(repo, "update-ref", ref or f"refs/remotes/origin/{on}", new)
    git(repo, "checkout", "-q", BRANCH)
    return new


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def moves(recorder: Recorder) -> list[str]:
    """The log lines that say a branch was moved."""
    return [line for line in recorder.logged if MOVED in line]
