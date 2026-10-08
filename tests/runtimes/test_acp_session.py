"""An ACP step records its session when it starts and resumes it where the agent
advertises `session/resume` and `session/list` and lists it; where it cannot, it raises
`SessionUnavailable` and sends no prompt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.base import SessionUnavailable
from tests.runtimes.acp_agent import ANSWER, SESSION, requests, use_agent

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


def test_a_listed_session_is_resumed_and_no_new_one_is_opened(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=(EARLIER,))
    told: list[str] = []

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_session=told.append))

    assert result.ok is True
    [resumed] = requests(record, "session/resume")
    assert resumed["sessionId"] == EARLIER
    assert resumed["cwd"] == str(worktree)
    assert requests(record, "session/new") == []
    [prompt] = requests(record, "session/prompt")
    assert prompt["sessionId"] == EARLIER, "the step continues in the resumed session"
    assert result.session_id == EARLIER
    assert told == [EARLIER]


def test_the_listing_is_asked_for_the_worktrees_sessions_before_the_resume(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=(EARLIER,))

    AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    [listed] = requests(record, "session/list")
    assert listed["cwd"] == str(worktree)
    methods = [
        json.loads(line)["method"] for line in record.read_text().splitlines() if line.strip()
    ]
    assert methods.index("session/list") < methods.index("session/resume")


def test_an_unlisted_session_is_not_resumed_and_gets_no_prompt(
    tmp_path: Path, worktree: Path
) -> None:
    """An agent may answer a resume of an id it lacks by quietly starting a session, so the
    continuation prompt would reach a cold agent: the listing is what prevents it, and the
    caller starts the new session with the full prompt."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=("sess_other",))
    told: list[str] = []

    with pytest.raises(SessionUnavailable, match=f"{EARLIER} not resumed"):
        AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_session=told.append))

    assert len(requests(record, "session/list")) == 1
    assert requests(record, "session/resume") == []
    assert requests(record, "session/new") == [], "a new session is the caller's to start"
    assert requests(record, "session/prompt") == []
    assert told == []


def test_a_session_on_a_later_page_is_found_by_following_the_cursor(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    held = ("sess_a", "sess_b", EARLIER, "sess_d")
    use_agent(record, resume=True, list_sessions=True, sessions=held, page_size=2)

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    pages = requests(record, "session/list")
    assert len(pages) == 2
    assert not pages[0].get("cursor")
    assert pages[1]["cursor"] == "2", "the cursor the first page answered with"
    [resumed] = requests(record, "session/resume")
    assert resumed["sessionId"] == EARLIER
    assert result.session_id == EARLIER


def test_the_pages_are_followed_to_their_end_before_a_session_is_given_up_on(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(
        record,
        resume=True,
        list_sessions=True,
        sessions=("sess_a", "sess_b", "sess_c"),
        page_size=1,
    )

    with pytest.raises(SessionUnavailable):
        AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert len(requests(record, "session/list")) == 3
    assert requests(record, "session/resume") == []


@pytest.mark.parametrize(
    ("resume", "listing"),
    [
        pytest.param(True, False, id="resume-without-list"),
        pytest.param(False, True, id="list-without-resume"),
        pytest.param(False, False, id="neither"),
    ],
)
def test_an_agent_advertising_less_than_both_capabilities_is_not_resumed_and_not_an_error(
    tmp_path: Path, worktree: Path, resume: bool, listing: bool
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=resume, list_sessions=listing, sessions=(EARLIER,))
    told: list[str] = []

    with pytest.raises(SessionUnavailable, match=f"{EARLIER} not resumed"):
        AcpRuntime().run(_request(worktree, resume_session=EARLIER, on_session=told.append))

    assert requests(record, "session/resume") == []
    assert requests(record, "session/new") == [], "a new session is the caller's to start"
    assert requests(record, "session/prompt") == []
    assert told == []


def test_session_load_is_never_called_even_where_the_agent_declares_it(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, load_session=True, resume=True, list_sessions=True, sessions=(EARLIER,))

    AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    use_agent(record, load_session=True)
    with pytest.raises(SessionUnavailable):
        AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert requests(record, "session/load") == []


def test_what_a_resumed_session_answers_with_is_the_steps_answer(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=(EARLIER,))

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert result.text == ANSWER


def test_the_runtime_reports_resumable_only_to_the_agent_that_can_be(
    tmp_path: Path, worktree: Path
) -> None:
    """`supports_session_resume` is set from what the agent advertised at initialize, so a
    runtime that has spoken to an agent without both capabilities no longer claims it."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    runtime = AcpRuntime()

    with pytest.raises(SessionUnavailable):
        runtime.run(_request(worktree, resume_session=EARLIER))

    assert runtime.supports_session_resume is False

    use_agent(record, resume=True, list_sessions=True, sessions=(EARLIER,))
    runtime = AcpRuntime()
    runtime.run(_request(worktree, resume_session=EARLIER))

    assert runtime.supports_session_resume is True
