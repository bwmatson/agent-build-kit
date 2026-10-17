"""A hand-made scratch installation for the tests of the live-test helpers: a bare remote with
`main`, a state directory and an environment, and no process behind them."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from agent_build_kit.model import Frozen
from tests.factories import git


class HandScratch(Frozen):
    planning: Path
    remote: Path
    state: Path
    env: dict[str, str] = Field(repr=False)


def hand_scratch(tmp_path: Path, *, branch: str | None = None) -> HandScratch:
    """A scratch whose remote holds `main` and, when `branch` is given, that branch with two
    commits on top of it (their ids are `commits_on(scratch, branch)`)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(remote, "config", "core.logAllRefUpdates", "always")
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "base").write_text("base")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", str(remote), "main")
    if branch:
        git(work, "checkout", "-q", "-b", branch)
        for number in (1, 2):
            (work / f"f{number}").write_text(str(number))
            git(work, "add", "-A")
            git(work, "commit", "-q", "-m", f"work {number}")
        git(work, "push", "-q", str(remote), branch)
    state = tmp_path / "state"
    state.mkdir()
    return HandScratch(planning=tmp_path / "planning", remote=remote, state=state, env={})


def commits_on(scratch: HandScratch, branch: str) -> list[str]:
    """The ids of the commits `branch` has over `main` on the scratch's remote."""
    return git(scratch.remote, "log", "--format=%H", f"main..{branch}").split()
