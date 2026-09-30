"""A track phase's bookkeeping is committed by the runner, and the planning
repo stays on its default branch however the phase's agent behaves.

Each test runs a phase through `claude_phase` with an agent double that does
to the planning repo what an agent might, against real git repos: the planning
repo, a bare `origin` for it, and a second clone that stands in for anyone
else pushing.
"""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.tracks import runner
from tests.factories import git, init_repo
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import make_installation, project


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "origin.git"
    path.mkdir()
    git(path, "init", "-q", "--bare", "-b", "main")
    return path


@pytest.fixture
def inst(tmp_path: Path, remote: Path) -> Installation:
    installation = make_installation(tmp_path / "planning")
    planning = init_repo(installation.root)
    for name in ("one", "two"):
        (planning / f"{name}.md").write_text(name)
        git(planning, "add", "-A")
        git(planning, "commit", "-q", "-m", name)
    git(planning, "remote", "add", "origin", str(remote))
    git(planning, "push", "-q", "-u", "origin", "main")
    return installation


def write_run_log(inst: Installation, phase: str = "health") -> Path:
    path = runner.run_log(inst, project(inst), phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Run log\n\n**Status:** OK\n")
    return path


def doing(inst: Installation, *steps: Callable[[], None]) -> StandInRuntime:
    """An agent double that runs `steps`, then writes its run log."""

    def act(request: AgentRequest) -> None:
        if request.worktree is not None:
            return
        for step in steps:
            step()
        write_run_log(inst)

    return StandInRuntime(act=act)


def phase(inst: Installation, runtime: StandInRuntime) -> int:
    return runner.claude_phase(inst, project=project(inst), name="health", runtime=runtime)


def count(repo: Path, ref: str = "main") -> int:
    return int(git(repo, "rev-list", "--count", ref))


def branch_of(repo: Path) -> str:
    return git(repo, "symbolic-ref", "--short", "HEAD")


def log_name(inst: Installation) -> str:
    return runner.run_log(inst, project(inst), "health").relative_to(inst.root).as_posix()


# --- 1.1 the runner commits -------------------------------------------------------


def test_a_phase_s_run_log_is_committed_by_the_runner(inst: Installation, remote: Path) -> None:
    planning = inst.root
    before = count(planning)

    assert phase(inst, doing(inst)) == 0

    assert count(planning) == before + 1
    assert branch_of(planning) == "main"
    assert git(planning, "show", "--name-only", "--format=", "main").splitlines() == [
        log_name(inst)
    ]
    message = git(planning, "log", "-1", "--format=%s", "main")
    assert runner.RUN_ID in message and "app" in message and "health" in message
    assert git(planning, "status", "--porcelain") == ""
    assert git(remote, "rev-parse", "main") == git(planning, "rev-parse", "main")


# --- 1.2 a rejected push ----------------------------------------------------------


def test_a_push_the_remote_rejected_is_retried_after_a_fast_forward(
    inst: Installation, remote: Path, tmp_path: Path
) -> None:
    def someone_else_pushes() -> None:
        other = tmp_path / "other"
        git(tmp_path, "clone", "-q", str(remote), str(other))
        git(other, "config", "user.email", "o@o.o")
        git(other, "config", "user.name", "o")
        (other / "theirs.md").write_text("theirs")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "theirs")
        git(other, "push", "-q", "origin", "main")

    (inst.root / "one.md").write_text("edited, not committed")

    phase(inst, doing(inst, someone_else_pushes))

    assert git(inst.root, "diff", "--name-only") == "one.md", "still dirty, not stashed away"
    assert (inst.root / "one.md").read_text() == "edited, not committed"
    assert git(remote, "show", f"main:{log_name(inst)}")
    assert git(remote, "show", "main:theirs.md") == "theirs"
    assert git(remote, "rev-parse", "main") == git(inst.root, "rev-parse", "main")


def test_a_second_rejection_is_reported_with_the_commit_kept(
    inst: Installation, remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    attempts = remote / "attempts"
    hook = remote / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\necho x >> {attempts}\necho 'remote says no' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    before = count(inst.root)

    phase(inst, doing(inst))

    assert len(attempts.read_text().splitlines()) == 2, "one push, and one retry"
    assert count(inst.root) == before + 1, "the commit stays in the planning repo"
    assert "push" in capsys.readouterr().out.lower()


# --- 1.3 a stray branch -----------------------------------------------------------


def test_a_planning_repo_moved_to_a_new_branch_is_put_back(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = inst.root
    before = count(planning)

    def switch() -> None:
        git(planning, "checkout", "-q", "-b", "feature-x")

    phase(inst, doing(inst, switch))

    assert branch_of(planning) == "main"
    assert count(planning) == before + 1
    assert git(planning, "show", f"main:{log_name(inst)}")
    assert git(planning, "branch", "--list", "feature-x") != "", "the stray branch is kept"
    assert "feature-x" in capsys.readouterr().out


# --- 1.4 a rewritten default branch -----------------------------------------------


def test_a_rewritten_default_branch_stops_the_run_and_commits_nothing(
    inst: Installation, remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = inst.root
    pushed = git(remote, "rev-parse", "main")

    def rewrite() -> None:
        git(planning, "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")

    runtime = doing(inst, rewrite)

    assert runner.DISPATCH["improve"](inst, project(inst), None, runtime=runtime) != 0

    assert len(runtime.requests) == 1, "the implement pass after it does not run"
    assert "rewritten" in capsys.readouterr().out.lower()
    assert git(planning, "log", "-1", "--format=%s", "main") == "rewritten"
    assert git(remote, "rev-parse", "main") == pushed
    assert git(planning, "status", "--porcelain") != "", "the run log is left uncommitted"
