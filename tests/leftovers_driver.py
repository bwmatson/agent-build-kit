"""A unit built in a real git worktree by an agent that edits files and can be killed.

The runner's worktree, commit and branch-count callables are the real ones over a
real repository; only the agent is a stand-in, reached through the real
`build_run`. `Hands` writes files into the worktree the way an agent does,
reports a session when asked to, and dies once in the step it was told to,
leaving a half-made edit behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.units import branch_name
from agent_build_kit.pipeline.wiring import (
    branch_commits,
    build_commit,
    build_run,
    build_worktree,
)
from agent_build_kit.pipeline.workspaces import worktree_path
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import SessionUnavailable
from tests.factories import init_repo, unit
from tests.runner_fakes import Killed
from tests.runtimes.stand_in import StandInRuntime

LEFTOVER = "partial.txt"


def step_of(prompt: str) -> str:
    """The node a prompt was written for."""
    if prompt.startswith("The process running you"):
        return "resumed"
    if "test tasks" in prompt:
        return "tests"
    if "checks (lint" in prompt:
        return "fix_checks"
    if "Review asked for" in prompt or "review of this branch" in prompt:
        return "rework"
    return "implement"


class Hands(StandInRuntime):
    """An agent that writes `<step>.txt` in its worktree and dies once in `die_in`.

    The death comes after a half-made edit (`partial.txt`, and `extra` more files),
    and after the session id was reported unless `names_session_first` is false;
    with `sessions` false the runtime reports no session at all."""

    def __init__(
        self,
        *,
        die_in: str = "",
        dies: BaseException | None = None,
        sessions: bool = True,
        names_session_first: bool = True,
        resumes: bool = True,
        refuses: str = "",
        extra: int = 0,
        edits: bool = True,
    ) -> None:
        super().__init__(answer="done")
        self.die_in = die_in
        self.dies = dies if dies is not None else Killed("power loss")
        self.sessions = sessions
        self.names_session_first = names_session_first
        self.supports_session_resume = resumes
        self.refuses = refuses
        self.extra = extra
        self.edits = edits
        self.died = False
        self.act = self.behave

    def behave(self, request: AgentRequest) -> None:
        cwd = request.cwd
        assert cwd is not None
        if request.resume_session and self.refuses:
            raise SessionUnavailable(self.refuses)
        step = "resumed" if request.resume_session else step_of(request.prompt)
        dying = step == self.die_in and not self.died
        if self.sessions and request.on_session and (self.names_session_first or not dying):
            request.on_session(request.resume_session or f"sess-{len(self.requests)}")
        if dying:
            self.died = True
            if self.edits:
                (cwd / LEFTOVER).write_text("half an edit\n")
                for n in range(self.extra):
                    (cwd / f"leftover-{n:02d}.txt").write_text("more\n")
            raise self.dies
        finished = self.die_in if step == "resumed" else step
        (cwd / f"{finished}.txt").write_text("done\n")

    def after_death(self) -> list[AgentRequest]:
        """Every request after the one that died."""
        first = next(
            index
            for index, request in enumerate(self.requests)
            if step_of(request.prompt) == self.die_in
        )
        return self.requests[first + 1 :]


class Habitat:
    """A repository on `main`, its worktrees, and the callables over them."""

    def __init__(self, tmp_path: Path, runtime: Hands) -> None:
        self.runtime = runtime
        self.repo = init_repo(tmp_path / "app")
        (self.repo / "README.md").write_text("app\n")
        git_out(self.repo, "add", "-A")
        git_out(self.repo, "commit", "-q", "-m", "start")
        # The trunk is built on from the remote's ref, which a fixture has no remote for.
        git_out(self.repo, "update-ref", "refs/remotes/origin/main", "main")
        self.trees = tmp_path / "trees"

    def overrides(self) -> dict[str, Any]:
        agent = build_run(runtime=self.runtime)
        return dict(
            worktree=build_worktree({"app": self.repo}, root=self.trees),
            commit=build_commit(unit_id=unit().id),
            head=lambda cwd: git_out(cwd, "rev-parse", "HEAD"),
            branch_commits=lambda cwd, base: branch_commits(cwd, base),
            run=agent,
        )

    @property
    def tree(self) -> Path:
        return worktree_path(self.repo, branch_name(unit()), self.trees)

    def commits_on_branch(self) -> list[str]:
        """The subjects of the branch's commits beyond `main`, oldest first."""
        log = git_out(self.tree, "log", "--reverse", "--format=%s", "origin/main..HEAD")
        return log.splitlines()

    def files_in(self, subject: str) -> list[str]:
        """The files of the branch's commit whose subject starts with `subject`."""
        log = git_out(self.tree, "log", "--format=%H\t%s", "origin/main..HEAD")
        sha = next(
            line.split("\t")[0]
            for line in log.splitlines()
            if line.split("\t")[1].startswith(subject)
        )
        return git_out(self.tree, "show", "--name-only", "--format=", sha).splitlines()
