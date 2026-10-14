"""A turn is read through the in-process client without a socket opening (spec: chat-tests).

The guard in `test_no_sockets_in_tier1.py` reads the source; this runs the application with
every way of opening a socket refused, so one made at run time (a server started in the
application's lifespan, a client built in a dependency) fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from tests.chat_serving import in_process_client, recorded_acp_session, turn, unit_worktree
from tests.runtimes.acp_agent import SESSION
from tests.runtimes.in_process_acp import use_in_process_agent
from tests.serving import seed_pipeline

RECORDED = "sess_0123456789abcdef"


def test_a_seeded_turn_is_read_without_a_socket_opening(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    recorded_acp_session(inst, RECORDED)
    use_in_process_agent(monkeypatch, tmp_path / "agent.jsonl")
    attempts: list[str] = []

    def refuse(name: str):
        def refused(*args: object, **kwargs: object) -> None:
            attempts.append(name)
            raise AssertionError(f"socket.{name} was called")

        return refused

    for name in ("connect", "connect_ex", "bind", "listen"):
        monkeypatch.setattr(f"socket.socket.{name}", refuse(name))

    with in_process_client(inst) as api:
        events = turn(api, f"/api/sessions/acp/{RECORDED}/continue", {"tab": "t1", "prompt": "Hi."})

    assert any(
        e["type"] == "CUSTOM" and e["name"] == "session" and e["value"]["id"] == SESSION
        for e in events
    )
    assert attempts == []
