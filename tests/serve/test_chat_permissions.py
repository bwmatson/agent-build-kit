"""A permission request from a turn waits for the browser, and closing the page denies it.

The agent is a real process speaking the Agent Client Protocol (`tests/runtimes/acp_agent.py`),
which asks to run a command and records what it was answered.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit.installation import Installation
from tests.chat_serving import WAIT, events_of, record_session, unit_worktree, until
from tests.runtimes.acp_agent import SESSION, requests, use_agent
from tests.serving import seed_pipeline

REVIEW = "/api/units/feature/2"
# A session id on a command line (an editor holding it, a fake agent listing it) is seen by
# every server on the machine, so these cannot run beside each other.
pytestmark = pytest.mark.serial

ASK = [{"ask": "execute", "command": "ls src"}]


@pytest.fixture
def record(inst: Installation, tmp_path: Path) -> Path:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    record_session(inst, "feature/2", SESSION, runtime="acp")
    path = tmp_path / "agent.jsonl"
    use_agent(path, resume=True, list_sessions=True, sessions=(SESSION,), act=ASK)
    return path


def request_of(events: Any) -> dict[str, Any]:
    for event in events:
        if event["type"] == "CUSTOM" and event["name"] == "permission_request":
            return event["value"]
    raise AssertionError("the turn never asked for permission")


def test_a_request_is_shown_with_its_options_and_the_turn_waits(
    record: Path, api: httpx.Client
) -> None:
    with api.stream(
        "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}, timeout=WAIT
    ) as reply:
        ask = request_of(events_of(reply))

        assert ask["tool"] and "ls src" in str(ask["input"])
        assert {o["kind"] for o in ask["options"]} == {
            "allow_once",
            "reject_once",
            "reject_always",
        }, "an always-allow would stop the agent asking, and abk's rules would not see its calls"
        assert requests(record, "did/ask") == [], "the agent is still waiting for an answer"
        assert requests(record, "did/run") == []


def test_the_answer_from_the_browser_goes_to_the_agent(record: Path, api: httpx.Client) -> None:
    with api.stream(
        "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}, timeout=WAIT
    ) as reply:
        events = events_of(reply)
        ask = request_of(events)
        once = next(o["id"] for o in ask["options"] if o["kind"] == "allow_once")

        answered = api.post(f"/api/permissions/{ask['id']}", json={"option": once})
        rest = list(events)

    assert answered.status_code in (200, 204)
    assert rest[-1]["type"] == "RUN_FINISHED"
    [asked] = requests(record, "did/ask")
    assert asked["optionKind"] == "allow_once"
    assert len(requests(record, "did/run")) == 1


def test_a_refusal_from_the_browser_denies_the_command(record: Path, api: httpx.Client) -> None:
    with api.stream(
        "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}, timeout=WAIT
    ) as reply:
        events = events_of(reply)
        ask = request_of(events)
        no = next(o["id"] for o in ask["options"] if o["kind"] == "reject_once")

        api.post(f"/api/permissions/{ask['id']}", json={"option": no})
        list(events)

    [asked] = requests(record, "did/ask")
    assert asked["optionKind"] == "reject_once"
    assert requests(record, "did/run") == []


def test_closing_the_page_with_a_request_outstanding_denies_it(
    record: Path, api: httpx.Client
) -> None:
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}, timeout=WAIT) as page:
        page_events = events_of(page)  # kept: dropping the iterator would close the stream
        next(page_events)
        with api.stream(
            "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}, timeout=WAIT
        ) as reply:
            events = events_of(reply)
            request_of(events)

            page.close()

            assert until(lambda: requests(record, "did/ask"))
            list(events)

    [asked] = requests(record, "did/ask")
    assert asked["outcome"] == "cancelled" or str(asked["optionKind"]).startswith("reject")
    assert requests(record, "did/run") == [], "the command never ran"


def test_an_always_answer_the_browser_was_never_offered_does_not_allow_anything(
    record: Path, api: httpx.Client
) -> None:
    with api.stream(
        "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}, timeout=WAIT
    ) as reply:
        events = events_of(reply)
        ask = request_of(events)

        api.post(f"/api/permissions/{ask['id']}", json={"option": "proceed_always"})
        list(events)

    assert requests(record, "did/run") == []
    [asked] = requests(record, "did/ask")
    assert asked["optionKind"] != "allow_always"


def test_stopping_the_server_with_a_request_outstanding_and_the_page_open_denies_it_and_returns(
    record: Path, inst: Installation
) -> None:
    from agent_build_kit.serve.server import start_server

    with start_server(inst) as server:
        client = httpx.Client(base_url=server.url, timeout=WAIT)
        page = client.send(
            client.build_request("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}),
            stream=True,
        )
        page_events = events_of(page)
        next(page_events)
        reply = client.send(
            client.build_request(
                "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "List it."}
            ),
            stream=True,
        )
        replies = events_of(reply)
        request_of(replies)
        assert requests(record, "did/ask") == [], "the agent is waiting on the page"
        left = time.monotonic()

    stopped_in = time.monotonic() - left
    try:
        assert stopped_in < 8, "uvicorn waited on the open requests"
        assert until(lambda: requests(record, "did/ask"))
        [asked] = requests(record, "did/ask")
        assert asked["outcome"] == "cancelled" or str(asked["optionKind"]).startswith("reject")
        assert requests(record, "did/run") == []
    finally:
        page.close()
        reply.close()
        client.close()
