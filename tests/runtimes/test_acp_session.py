"""An ACP step records its session when it starts and resumes it where the agent
can load one; where it cannot, it starts a new session and says so."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import ANSWER, EARLIER_TURN, SESSION, requests, use_agent

EARLIER = "sess_Ln3Vt8QaRcXe5mJd"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    path.mkdir()
    return path


def _request(worktree: Path, **fields: object) -> AgentRequest:
    return AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, **fields)  # pyrefly: ignore


def test_the_session_id_is_reported_when_the_session_starts(tmp_path: Path, worktree: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    told: list[tuple[str, int]] = []

    def on_session(session_id: str) -> None:
        told.append((session_id, len(requests(record, "session/prompt"))))

    AcpRuntime().run(_request(worktree, on_session=on_session))

    assert told == [(SESSION, 0)], "once, and before the prompt, so a killed run still has it"


def test_a_failed_turn_still_reported_its_session(tmp_path: Path, worktree: Path) -> None:
    use_agent(tmp_path / "agent.jsonl", stop="max_tokens")
    told: list[str] = []

    AcpRuntime().run(_request(worktree, on_session=told.append))

    assert told == [SESSION]


def test_a_run_with_no_session_to_resume_opens_a_new_one(tmp_path: Path, worktree: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, load_session=True)

    AcpRuntime().run(_request(worktree))

    assert len(requests(record, "session/new")) == 1
    assert requests(record, "session/load") == []


def test_an_agent_that_declares_session_loading_loads_the_recorded_session(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, load_session=True)
    told: list[str] = []

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_session=told.append))

    assert result.ok is True
    [loaded] = requests(record, "session/load")
    assert loaded["sessionId"] == EARLIER
    assert loaded["cwd"] == str(worktree)
    assert requests(record, "session/new") == []
    [prompt] = requests(record, "session/prompt")
    assert prompt["sessionId"] == EARLIER, "the step continues in the loaded session"
    assert result.session_id == EARLIER
    assert told == [EARLIER]


def test_the_history_a_load_replays_is_not_the_steps_answer(tmp_path: Path, worktree: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, load_session=True)

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert len(requests(record, "session/load")) == 1
    assert result.text == ANSWER
    assert EARLIER_TURN not in result.text


def test_an_agent_that_does_not_declare_session_loading_gets_a_new_session(
    tmp_path: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    told: list[str] = []

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_session=told.append))

    assert result.ok is True
    assert requests(record, "session/load") == []
    assert len(requests(record, "session/new")) == 1
    assert result.session_id == SESSION
    assert told == [SESSION]
    [said] = [line for line in capsys.readouterr().err.splitlines() if EARLIER in line]
    assert "not resumed" in said


def test_the_notice_that_a_session_was_not_resumed_reaches_the_runs_log(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl")
    logged: list[str] = []

    AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_event=logged.append))

    assert any(EARLIER in line and "not resumed" in line for line in logged)
