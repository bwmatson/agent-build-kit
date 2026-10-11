"""Every agent call, on every path it can take and under every runtime, writes exactly one
ledger row (spec: unit-timeline-is-recorded, Every agent call writes exactly one ledger row).

The runtimes are the real Claude Code runtime over a faked `claude` process and the real ACP
runtime over a small agent speaking the protocol on stdio; a thin proxy counts the calls that
finished, and a call that dies before it finishes is a call that wrote nothing.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.graph.test_session_continuation import failing_checks
from tests.graph.test_usage_ledger_records import ledger_lines
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Killed
from tests.runtimes.acp_agent import SESSION as ACP_SESSION
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import FakeClaude, finished_build

CLAUDE = "claude_code"
ACP = "acp"


class Counted:
    """A real runtime that counts the calls that finished and keeps each request it got. The
    call numbered `die_on` (from 1) runs for real and announces its session, then dies before
    it reports a result, as a power loss does: it leaves a session id and no row."""

    def __init__(self, inner: Any, *, die_on: int = 0) -> None:
        self.inner = inner
        self.die_on = die_on
        self.requests: list[AgentRequest] = []
        self.sessions: list[str] = []
        self.finished = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        if len(self.requests) != self.die_on:
            result = self.inner.run(request)
            self.finished += 1
            return result

        def announce(session: str) -> None:
            self.sessions.append(session)
            if request.on_session:
                request.on_session(session)

        self.inner.run(request.model_copy(update={"on_session": announce, "on_result": None}))
        raise Killed("power loss")


def runtime_of(kind: str, tmp_path: Path, *, die_on: int = 0) -> Counted:
    if kind == CLAUDE:
        fake = FakeClaude(stdout=finished_build(tmp_path, "done"))
        return Counted(ClaudeCodeRuntime(execute=fake), die_on=die_on)
    (tmp_path / "tree").mkdir(exist_ok=True)  # the worktree the runner hands the agent
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=(ACP_SESSION,))
    return Counted(AcpRuntime(), die_on=die_on)


@pytest.mark.parametrize("kind", [CLAUDE, ACP])
def test_a_new_call_writes_one_row(tmp_path: Path, workspace: Installation, kind: str) -> None:
    runtime = runtime_of(kind, tmp_path)

    outcome = tick(tmp_path, fresh(tmp_path), run=build_run(runtime=runtime))  # pyrefly: ignore

    assert outcome.status == RunStatus.OPEN
    assert runtime.finished == 2
    assert Counter(r["node"] for r in ledger_lines(workspace)) == {"tests": 1, "implement": 1}


@pytest.mark.parametrize("kind", [CLAUDE, ACP])
def test_a_resumed_call_writes_one_row(tmp_path: Path, workspace: Installation, kind: str) -> None:
    runtime = runtime_of(kind, tmp_path, die_on=2)
    recorder = fresh(tmp_path)
    run = build_run(runtime=runtime)  # pyrefly: ignore
    with pytest.raises(Killed):
        tick(tmp_path, recorder, run=run)

    tick(tmp_path, recorder, run=run)

    (session,) = runtime.sessions
    retry = runtime.requests[2]
    assert retry.resume_session == session, "the retry continues the session the killed call opened"
    assert runtime.finished == 2, "the killed call finished nothing; its retry is the second"
    records = ledger_lines(workspace)
    assert Counter(r["node"] for r in records) == {"tests": 1, "implement": 1}
    assert len(records) == runtime.finished


@pytest.mark.parametrize("kind", [CLAUDE, ACP])
def test_a_continued_call_writes_one_row(
    tmp_path: Path, workspace: Installation, kind: str
) -> None:
    runtime = runtime_of(kind, tmp_path)
    recorder = fresh(tmp_path)
    failing_checks(recorder)

    tick(tmp_path, recorder, run=build_run(runtime=runtime))  # pyrefly: ignore

    assert runtime.requests[2].resume_session, "the fix continues the build session"
    assert runtime.finished == 3, "tests, implement, and the fix that continues the session"
    records = ledger_lines(workspace)
    assert len(records) == runtime.finished
    assert Counter(r["node"] for r in records) == {"tests": 1, "implement": 1, "fix_checks": 1}
