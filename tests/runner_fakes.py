"""The injected fakes the build-path tests of the graph engine drive a runner with.

A fake stands where `wiring.build_runner` binds a real callable. The fake
remote and forge keep what was published, which is what lets a test say a
re-run did nothing twice.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit


class Killed(BaseException):
    """The process dying: not an error a node may catch."""


class Recorder:
    """Stands in for every side effect, recording what happened in order."""

    tier1_output: str = ""

    def __init__(
        self,
        store: UnitStore,
        *,
        commits_from_impl: int = 1,
        tier1_ok: bool = True,
        kill_after: str = "",
        push_raises: Exception | None = None,
        rework_answer: str = "done",
        tier2_ok: bool = True,
        close_error: str = "",
    ):
        self.store = store
        self.events: list[str] = []
        self.prompts: list[str] = []
        self.logged: list[str] = []
        self.verdicts: list[str] = []
        self.commits_from_impl = commits_from_impl
        self.tier1_ok = tier1_ok
        self.kill_after = kill_after
        self.push_raises = push_raises
        self.rework_answer = rework_answer  # what the builder says of a review's ask
        self.tier2_ok = tier2_ok
        self.tier2_output = "## Tier 2 results\nfine"
        self.close_error = close_error
        self.closed: list[tuple[str, int, str]] = []  # (unit, pull request, reason)
        # Answers for successive tier 1 runs, in order; once spent, `tier1_ok`.
        self.tier1_results: list[tuple[bool, str]] = []
        self.made = 0
        self.remote: list[str] = []  # every distinct head the remote has been given
        self.prs: dict[str, int] = {}  # branch -> pull request, as the forge holds them
        self.pr_calls = 0
        self.pr_opens = 0  # calls that found no pull request for the branch
        self.contexts: list[str] = []  # what each review was given

    def _after(self, event: str) -> None:
        """Record `event`, then die once if the test asked for that."""
        self.events.append(event)
        if self.kill_after == event:
            self.kill_after = ""
            raise Killed(event)

    def claude(
        self,
        prompt: str,
        *,
        cwd: Path,
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        if "checks (lint" in prompt:
            self.events.append("claude:fix_checks")
        elif "Review asked for" in prompt or "review of this branch" in prompt:
            self.events.append("claude:rework")
            return self.rework_answer
        else:
            self.events.append("claude:tests" if "test tasks" in prompt else "claude:impl")
        return "done"

    def review(
        self,
        *,
        cwd: Path,
        context: str = "",
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> str:
        self.contexts.append(context)
        self.events.append("review")
        return self.verdicts.pop(0) if self.verdicts else approving()

    def commit(self, message: str, *, cwd: Path) -> int:
        count = 1 if "test" in message else self.commits_from_impl
        self.made += count
        self._after(f"commit:{message.split(':')[0]}")
        return count

    def branch_commits(self, cwd: Path, base: str) -> int:
        return self.made

    def head(self, cwd: Path) -> str:
        return f"sha-{self.made}"

    def tier1(self, *, cwd: Path, base: str = "main", whole_repo: bool = False) -> tuple[bool, str]:
        self.events.append("tier1:whole_repo" if whole_repo else "tier1")
        if self.tier1_results:
            return self.tier1_results.pop(0)
        return self.tier1_ok, self.tier1_output

    def tier2(self, *, cwd: Path) -> tuple[bool, str]:
        self.events.append("tier2")
        return self.tier2_ok, self.tier2_output

    def push(self, branch: str, *, cwd: Path) -> str:
        if self.push_raises:
            raise self.push_raises
        sha = self.head(cwd)
        if sha not in self.remote:
            self.remote.append(sha)
        self.store.record_push(unit().id, sha)
        self._after("push")
        return sha

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        """Opens on the first call, updates on later ones, as the forge does."""
        self.pr_calls += 1
        if f"spec/{unit.id}" not in self.prs:
            self.pr_opens += 1
            self.prs[f"spec/{unit.id}"] = 7
        self._after("pr")
        return self.prs[f"spec/{unit.id}"]

    def post_status(self, sha: str, ok: bool) -> None:
        self.events.append("status")

    def close_pr(self, unit, pr: int, reason: str) -> None:
        self.events.append("close")
        if self.close_error:
            raise RuntimeError(self.close_error)
        self.closed.append((unit.id, pr, reason))

    def log(self, message: str) -> None:
        self.logged.append(message)


def approving() -> str:
    return json.dumps({"approved": True, "feedback": ""})


def rejecting(reason: str) -> str:
    return json.dumps({"approved": False, "feedback": reason})


def make_runner(
    store: UnitStore, recorder: Recorder, tmp_path: Path, **overrides: Any
) -> UnitRunner:
    """A runner over the recorder's fakes; `overrides` replace any callable."""
    wired: dict[str, Any] = dict(
        store=store,
        planning_repo=tmp_path / "meta",
        worktree=lambda u, base: tmp_path / "tree",
        may_start=lambda: (True, "usage fine"),
        run_claude=recorder.claude,
        run_rework=recorder.claude,
        run_review=recorder.review,
        run_rework_review=recorder.review,
        commit=recorder.commit,
        branch_commits=recorder.branch_commits,
        head=recorder.head,
        upstream_incomplete=lambda u: "",
        restack_onto=lambda **kw: None,
        run_tier1=recorder.tier1,
        run_tier2=recorder.tier2,
        push=recorder.push,
        open_pr=recorder.open_pr,
        post_status=recorder.post_status,
        close_pr=recorder.close_pr,
        log=recorder.log,
    )
    return UnitRunner(**{**wired, **overrides})
