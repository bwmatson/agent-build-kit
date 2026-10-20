"""A chat turn on a unit's own build session, when the agent cannot resume that session.

An ACP agent that does not advertise `session/resume` (or does not list the session) cannot
continue the build session in place. The turn then goes on in a new session seeded with the
recorded history, as the sessions page does, and says so with a `continued_as_new` event. The
agent is the in-process fake (`tests/runtimes/in_process_acp.py`); see `tests/chat_serving.py`
for the endpoints.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from tests.chat_serving import record_session, recorded_acp_session, turn, unit_worktree
from tests.runtimes.acp_agent import EARLIER_TURN, SESSION, requests
from tests.runtimes.in_process_acp import use_in_process_agent
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = f"sess_{uuid.uuid4().hex[:16]}"
UNIT = "/api/units/feature/2"


def test_a_build_session_the_agent_cannot_resume_goes_on_in_a_new_seeded_session(
    inst: Installation, tmp_path: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    record_session(inst, "feature/2", BUILD_SESSION, runtime="acp")
    recorded_acp_session(inst, BUILD_SESSION)
    record = tmp_path / "agent.jsonl"
    use_in_process_agent(monkeypatch, record)

    events = turn(api, f"{UNIT}/chat", {"tab": "t1", "prompt": "Carry on."})

    assert any(e["type"] == "CUSTOM" and e["name"] == "continued_as_new" for e in events)
    assert requests(record, "session/resume") == [], "the agent cannot resume, so no resume is sent"
    assert len(requests(record, "session/new")) == 1
    [prompted] = requests(record, "session/prompt")
    assert prompted["sessionId"] == SESSION != BUILD_SESSION
    said = " ".join(block.get("text", "") for block in prompted["prompt"])
    assert "Carry on." in said
    assert EARLIER_TURN in said, "the new session is seeded with the build session's record"
    assert not any(e["type"] == "RUN_ERROR" for e in events), "the turn did not fail"
