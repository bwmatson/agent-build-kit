"""An ACP agent that lives in the test's own process, for the tests that are not about the
agent process.

`FakeAcpRuntime` stands where the registry hands out the `acp` runtime and answers what the
chat layer asks of it (`run`, `can_resume_session`) the way `AcpRuntime` answers against
`tests/runtimes/acp_agent.py`: a session is resumed only when the agent advertises resume and
list and lists the id, and anything else is `SessionUnavailable`. What the agent received is
appended to a record in the stub agent's own shape (`{"method", "params"}`, read with its
`requests`), so a test asserts on the same lines whichever of the two it runs against.
Nothing is spawned and nothing waits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.base import AgentRequest, AgentResult, SessionUnavailable
from tests.runtimes.acp_agent import ANSWER, DEFAULT_MODEL, MODEL_AT_PROMPT, SESSION


class FakeAcpRuntime(AcpRuntime):
    """The agent's answers are set by the test: whether it advertises resume and list, and the
    sessions it holds."""

    def __init__(
        self,
        record: Path,
        *,
        resume: bool = False,
        list_sessions: bool = False,
        sessions: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._record = record
        self._resume = resume
        self._list = list_sessions
        self._sessions = sessions

    def _write(self, method: str, params: dict) -> None:
        with self._record.open("a") as out:
            out.write(json.dumps({"method": method, "params": params}) + "\n")

    def can_resume_session(self, session_id: str, cwd: Path, *, environment=None) -> bool:
        return self._resume and self._list and session_id in self._sessions

    def run(self, request: AgentRequest) -> AgentResult:
        cwd = str(request.cwd or Path.cwd())
        if request.resume_session:
            if not self.can_resume_session(request.resume_session, Path(cwd)):
                raise SessionUnavailable(f"session {request.resume_session} not resumed")
            self._write("session/resume", {"sessionId": request.resume_session, "cwd": cwd})
            session = request.resume_session
        else:
            self._write("session/new", {"cwd": cwd})
            session = SESSION
        if request.on_session is not None:
            request.on_session(session)
        self._write(MODEL_AT_PROMPT, {"model": request.model or DEFAULT_MODEL})
        self._write(
            "session/prompt",
            {"sessionId": session, "prompt": [{"type": "text", "text": request.prompt}]},
        )
        if request.on_record is not None:
            request.on_record(TranscriptEvent(kind="text", session=session, text=ANSWER))
            request.on_record(TranscriptEvent(kind="stop", session=session, text="end_turn"))
        return AgentResult(ok=True, text=ANSWER, stop_reason="end_turn", turns=1)


def use_in_process_agent(
    monkeypatch: pytest.MonkeyPatch,
    record: Path,
    *,
    resume: bool = False,
    list_sessions: bool = False,
    sessions: tuple[str, ...] = (),
) -> FakeAcpRuntime:
    """Have the `acp` runtime be a `FakeAcpRuntime` writing to `record`."""
    fake = FakeAcpRuntime(record, resume=resume, list_sessions=list_sessions, sessions=sessions)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "acp", fake)
    return fake
