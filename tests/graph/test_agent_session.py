"""An agent node records its session id as soon as the runtime reports it, and a
node killed mid-agent resumes that session on the next tick, or falls back to a
new one (docs/unit-graph.md, Session capture and resume).

The agent is a runtime behind the `AgentRuntime` seam, reached through the real
`build_run`: what the nodes pass it and what it reports are what is
tested, not a stand-in for either.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_run, build_run_review
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import SessionUnavailable
from tests.factories import unit
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Killed, approving
from tests.runtimes.stand_in import StandInRuntime


class Sessions(StandInRuntime):
    """A runtime that numbers its sessions and dies in the first request, as a
    power loss does, once it has told its caller the session's id."""

    def __init__(self, *, resumes: bool = True, refuses: str = "", answer: str = "done") -> None:
        super().__init__(answer=answer)
        self.supports_session_resume = resumes
        self.refuses = refuses
        self.dies_once = True
        self.act = self.behave

    def behave(self, request: AgentRequest) -> None:
        if request.resume_session and self.refuses:
            raise SessionUnavailable(self.refuses)
        session = request.resume_session or f"sess-{len(self.requests)}"
        if request.on_session:
            request.on_session(session)
        if self.dies_once:
            self.dies_once = False
            raise Killed("power loss")


def run_log(tmp_path: Path) -> RunLog:
    return RunLog(
        tmp_path / "unit-logs",
        unit(),
        step="build",
        model="m",
        base="main",
        started=datetime.now(UTC),
    )


def logged(tmp_path: Path) -> str:
    return "\n".join(path.read_text() for path in (tmp_path / "unit-logs").iterdir())


def killed_in_the_tests_step(tmp_path: Path, runtime: Sessions):
    recorder = fresh(tmp_path)
    with pytest.raises(Killed):
        tick(tmp_path, recorder, run=build_run(runtime=runtime))
    return recorder


def test_the_session_id_is_in_the_threads_state_as_soon_as_the_runtime_reports_it(
    tmp_path: Path,
) -> None:
    runtime = Sessions()

    killed_in_the_tests_step(tmp_path, runtime)

    stopped = position(tmp_path)
    assert stopped.next == (Node.TESTS,)
    assert stopped.state is not None
    assert stopped.state.session_id == "sess-1"


def test_a_node_killed_mid_agent_resumes_its_session_with_the_interruption_note(
    tmp_path: Path,
) -> None:
    runtime = Sessions()
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    outcome = tick(tmp_path, recorder, run=build_run(runtime=runtime))

    assert outcome.status == RunStatus.OPEN
    killed, resumed, implementation = runtime.requests
    assert resumed.resume_session == "sess-1"
    note = resumed.prompt.lower()
    assert "interrupted" in note
    assert "re-read" in note
    assert resumed.prompt != killed.prompt, "the session already holds the original prompt"
    assert implementation.resume_session == "", "the next node starts its own session"
    assert recorder.store.get("add-marker/1").state == "in_review", "never requeued to planned"


def test_a_review_killed_mid_agent_resumes_its_session_too(tmp_path: Path) -> None:
    runtime = Sessions(answer=approving())
    recorder = fresh(tmp_path)
    with pytest.raises(Killed):
        tick(tmp_path, recorder, run_review=build_run_review(runtime=runtime))
    stopped = position(tmp_path)
    assert stopped.next == (Node.REVIEW,)
    assert stopped.state is not None
    assert stopped.state.session_id == "sess-1"

    outcome = tick(tmp_path, recorder, run_review=build_run_review(runtime=runtime))

    assert outcome.status == RunStatus.OPEN
    _, resumed = runtime.requests
    assert resumed.resume_session == "sess-1"
    assert "interrupted" in resumed.prompt.lower()


def test_a_session_id_is_cleared_when_its_node_completes(tmp_path: Path) -> None:
    runtime = Sessions()
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    tick(tmp_path, recorder, run=build_run(runtime=runtime))

    finished = position(tmp_path)
    assert finished.state is not None
    assert finished.state.session_id == ""


def test_a_runtime_without_session_resume_runs_the_node_from_its_start_and_says_so(
    tmp_path: Path,
) -> None:
    runtime = Sessions(resumes=False)
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    tick(
        tmp_path,
        recorder,
        run=build_run(runtime=runtime),
        run_log=run_log(tmp_path),
    )

    killed, again, *_ = runtime.requests
    assert again.resume_session == ""
    assert again.prompt == killed.prompt, "from the node's start"
    assert "new session" in logged(tmp_path).lower()


@pytest.mark.parametrize(
    "refusal",
    ["no conversation found with session id sess-1", "session expired: refused by the server"],
)
def test_a_session_the_runtime_cannot_resume_falls_back_to_a_new_one_and_says_so(
    tmp_path: Path, refusal: str
) -> None:
    runtime = Sessions(refuses=refusal)
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    outcome = tick(
        tmp_path,
        recorder,
        run=build_run(runtime=runtime),
        run_log=run_log(tmp_path),
    )

    assert outcome.status == RunStatus.OPEN
    killed, refused, fresh_start, *_ = runtime.requests
    assert refused.resume_session == "sess-1", "it was tried first"
    assert fresh_start.resume_session == ""
    assert fresh_start.prompt == killed.prompt, "from the node's start"
    assert "new session" in logged(tmp_path).lower()
