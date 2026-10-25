"""A confined step runs `git` in its worktree, and a review whose `git` stops on a refused read
fails as a sandbox fault naming the path (spec: sandbox-git-reads).

The backend is a stand-in that enforces the policy's lists on the paths `git` opens: what the
policy does not list is made unreadable, so the real `git` in a real linked worktree is refused
the way a sandbox would refuse it. File modes do not bind root, so the module is skipped there.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.pipeline.wiring import build_run, build_run_review
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.base import Role
from agent_build_kit.sandboxes import SandboxPolicy
from agent_build_kit.sandboxes.confinement import SandboxRefused
from tests.factories import commit, git
from tests.pipeline.test_wiring_sandbox import Recording, install

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root is not bound by file modes")

GIT_COMMANDS = (["git", "status"], ["git", "log", "-1"])


def allows(policy: SandboxPolicy, path: Path) -> bool:
    return any(path.resolve().is_relative_to(f) for f in (*policy.read, *policy.write))


@contextmanager
def unreadable(paths: list[Path]) -> Iterator[None]:
    """`paths` with no access, and their modes back afterwards so the folder can be removed."""
    modes = {path: stat.S_IMODE(path.stat().st_mode) for path in paths}
    try:
        for path in paths:
            path.chmod(0)
        yield
    finally:
        for path, mode in modes.items():
            path.chmod(mode)


class GitRunning(Recording):
    """Runs `git status` and `git log -1` where the step runs, with the paths `git` opens that the
    request's policy does not list made unreadable, and reports a failure as the tool result the
    agent's command printed."""

    def __init__(self, opened: list[Path]) -> None:
        super().__init__()
        self.opened = opened
        self.done: list[subprocess.CompletedProcess[str]] = []

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.policy is not None and request.policy.sandbox is not None
        policy = request.policy.sandbox
        refused = [path for path in self.opened if path.exists() and not allows(policy, path)]
        with unreadable(refused):
            for argv in GIT_COMMANDS:
                done = subprocess.run(argv, cwd=request.cwd, capture_output=True, text=True)
                self.done.append(done)
                if done.returncode != 0 and request.on_record:
                    request.on_record(TranscriptEvent(kind="tool_result", text=done.stderr))
        return super().run(request)


class Scene:
    """An installation with the sandbox on, a linked worktree of its repo and a home holding the
    person's git configuration."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        (self.home / ".config" / "git").mkdir(parents=True)
        (self.home / ".gitconfig").write_text("[user]\n\temail = t@t.t\n\tname = t\n")
        (self.home / ".config" / "git" / "ignore").write_text("*.swp\n")
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        self.root, self.main = install(tmp_path, enabled=True)
        commit(self.main, "a.txt")
        self.worktree = tmp_path / "wt"
        git(self.main, "worktree", "add", "-q", "-b", "unit", str(self.worktree))

    @property
    def common(self) -> Path:
        return self.main / ".git"

    def opened(self, *more: Path) -> list[Path]:
        """What `git status` opens in the worktree that a policy might leave unlisted."""
        return [
            self.common / "config",
            self.common / "info",
            self.common / "worktrees" / self.worktree.name,
            self.worktree / ".git",
            self.home / ".gitconfig",
            self.home / ".config" / "git" / "ignore",
            *more,
        ]

    def runtime(self, *more: Path) -> GitRunning:
        return GitRunning(self.opened(*more))

    def include_unlisted(self) -> Path:
        """A configuration file the repository's own includes, in a folder no policy lists."""
        extra = self.tmp / "elsewhere" / "extra.cfg"
        extra.parent.mkdir()
        extra.write_text("[core]\n\tabbrev = 9\n")
        git(self.main, "config", "include.path", str(extra))
        return extra


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def review(scene: Scene, runtime: GitRunning, role: Role = "review") -> str:
    return build_run_review(
        runtime=runtime, planning_repo=scene.root, sandbox_repo="app", role=role
    )(cwd=scene.worktree)


def test_a_confined_review_runs_git_status_and_log_in_the_worktree(scene: Scene) -> None:
    runtime = scene.runtime()

    review(scene, runtime)

    assert [d.returncode for d in runtime.done] == [0, 0], [d.stderr for d in runtime.done]


def test_a_confined_build_runs_git_status_and_log_in_the_worktree(scene: Scene) -> None:
    runtime = scene.runtime()

    build_run(runtime=runtime, planning_repo=scene.root, sandbox_repo="app")(
        "Go.", cwd=scene.worktree, model=models().implement
    )

    assert [d.returncode for d in runtime.done] == [0, 0], [d.stderr for d in runtime.done]


@pytest.mark.parametrize("role", ["review", "rework_review"])
def test_a_review_whose_git_stops_on_a_refused_read_fails_naming_the_path(
    scene: Scene, role: Role
) -> None:
    extra = scene.include_unlisted()
    runtime = scene.runtime(extra)

    with pytest.raises(SandboxRefused, match=re.escape(str(extra))):
        review(scene, runtime, role)

    assert any(str(extra) in d.stderr for d in runtime.done), "git named the refused path"
