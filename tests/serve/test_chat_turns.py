"""A running step is streamed and refuses input; once it ends a turn takes the lease.

The agent is the `claude` binary faked at its stream-json boundary. See
`tests/chat_serving.py` for the endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent, transcript_dir
from agent_build_kit.serve.server import start_server
from tests.chat_serving import (
    WAIT,
    events_of,
    prompt_of,
    record_session,
    turn,
    unit_worktree,
    until,
    use_claude,
)
from tests.factories import unit
from tests.runtimes.claude_cli import SESSION, finished_build
from tests.serving import seed_pipeline

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d31"
REVIEW = "/api/units/feature/2"
RUNNING = "/api/units/feature/7"


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    record_session(inst, "feature/2", BUILD_SESSION, runtime="claude_code")
    record_session(inst, "feature/7", SESSION, runtime="claude_code")
    return inst


def claude_for(monkeypatch: pytest.MonkeyPatch, inst: Installation, answer: str = "Hello."):
    return use_claude(monkeypatch, finished_build(unit_worktree(inst, "feature/2"), answer))


def test_a_running_step_disables_the_composer_with_the_reason(
    pipeline: Installation, api: httpx.Client
) -> None:
    tab = api.get(f"{RUNNING}/agent", params={"tab": "t1"}).json()

    assert tab["state"] == "streaming"
    assert tab["composer"]["enabled"] is False
    assert "running" in tab["composer"]["reason"].lower()


def test_input_to_a_running_step_is_refused_and_reaches_no_agent(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = claude_for(monkeypatch, pipeline)

    reply = api.post(f"{RUNNING}/chat", json={"tab": "t1", "prompt": "Stop and listen."})

    assert reply.status_code == 409
    assert fake.calls == []
    assert Leases(lease_dir(pipeline.state_dir)).holder("feature/7") is None


def test_a_running_step_is_streamed_as_it_records(pipeline: Installation) -> None:
    started = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
    step = Transcript(
        transcript_dir(pipeline.state_dir),
        unit("feature/7", change="feature"),
        node="implement",
        round=0,
        started=started,
        result_limit=1000,
        runs_kept=3,
    )
    with start_server(pipeline) as server, httpx.Client(base_url=server.url) as api:
        with api.stream(
            "GET", f"{RUNNING}/agent/events", params={"tab": "t1"}, timeout=WAIT
        ) as stream:
            events = events_of(stream)
            assert next(events)["type"] == "MESSAGES_SNAPSHOT"

            step.record(TranscriptEvent(kind="text", session=SESSION, text="Reading the module."))
            step.record(
                TranscriptEvent(
                    kind="tool_call", session=SESSION, tool="Read", call="c1", input={"file": "a"}
                )
            )

            seen = []
            for event in events:
                seen.append(event)
                if event["type"] == "TOOL_CALL_START":
                    break
    assert "Reading the module." in "".join(e.get("delta", "") for e in seen)
    assert seen[-1]["toolCallName"] == "Read"


def test_a_unit_between_steps_accepts_turns(pipeline: Installation, api: httpx.Client) -> None:
    tab = api.get(f"{REVIEW}/agent", params={"tab": "t1"}).json()

    assert tab["state"] == "paused"
    assert tab["session"]["id"] == BUILD_SESSION
    assert tab["composer"] == {"enabled": True, "reason": ""}


def test_a_turn_goes_to_the_units_session_and_takes_the_lease(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = claude_for(monkeypatch, pipeline)

    events = turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Why this approach?"})

    argv, cwd = fake.calls[0]
    assert argv[argv.index("--resume") + 1] == BUILD_SESSION
    assert "Why this approach?" in prompt_of(argv)
    assert cwd == unit_worktree(pipeline, "feature/2")
    assert events[-1]["type"] == "RUN_FINISHED"
    assert Leases(lease_dir(pipeline.state_dir)).holder("feature/2") == "tab:t1"
    tab = api.get(f"{REVIEW}/agent", params={"tab": "t1"}).json()
    assert tab["state"] == "attached"
    assert tab["attached_by"] == "tab:t1"


def test_another_tab_cannot_chat_while_the_lease_is_held(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = claude_for(monkeypatch, pipeline)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "First."})

    reply = api.post(f"{REVIEW}/chat", json={"tab": "t2", "prompt": "Second."})

    assert reply.status_code == 409
    assert len(fake.calls) == 1
    other = api.get(f"{REVIEW}/agent", params={"tab": "t2"}).json()
    assert other["composer"]["enabled"] is False


def test_releasing_the_lease_returns_the_unit_to_the_tick(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_for(monkeypatch, pipeline)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "First."})

    released = api.delete(f"{REVIEW}/lease", params={"tab": "t1"})

    assert released.status_code == 204
    assert Leases(lease_dir(pipeline.state_dir)).holder("feature/2") is None
    assert api.get(f"{REVIEW}/agent", params={"tab": "t1"}).json()["state"] == "paused"


def test_a_page_that_closes_releases_the_lease(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_for(monkeypatch, pipeline)
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}, timeout=WAIT) as stream:
        page_events = events_of(stream)  # kept: dropping the iterator would close the stream
        assert next(page_events)["type"] == "MESSAGES_SNAPSHOT"
        turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "First."})
        assert Leases(lease_dir(pipeline.state_dir)).holder("feature/2") == "tab:t1"

    assert until(lambda: Leases(lease_dir(pipeline.state_dir)).holder("feature/2") is None)
