"""Two writers never work on one session or one worktree: the lease outlives a turn its tab
started, a turn is refused while another runs on its session, a session a process has open is
read-only whether or not the process names it, and the live stream does not lose a step's
start when old transcripts are pruned.

The agents are faked at their wires (see `tests/chat_serving.py`).
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent, transcript_dir
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.agui_protocol import validate_stream
from tests.chat_serving import (
    WAIT,
    claude_session_file,
    claude_working_in,
    events_of,
    holding_process,
    prompt_of,
    record_session,
    turn,
    unit_worktree,
    until,
    use_blocking_claude,
    use_claude,
)
from tests.factories import unit
from tests.runtimes.acp_agent import SESSION as ACP_SESSION
from tests.runtimes.acp_agent import requests, use_agent
from tests.runtimes.claude_cli import finished_build
from tests.serving import seed_pipeline

# A session id on a command line (an editor holding it, a fake agent listing it) is seen by
# every server on the machine, so these cannot run beside each other.
pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d34"
OTHER_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e48"
REVIEW = "/api/units/feature/2"


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    record_session(inst, "feature/2", BUILD_SESSION, runtime="claude_code", model="opus")
    unit_worktree(inst, "feature/2")
    return inst


def holder(inst: Installation, unit_id: str = "feature/2") -> str | None:
    return Leases(lease_dir(inst.state_dir)).holder(unit_id)


# --- a closed page leaves no agent editing a worktree the tick has taken back ---------------


def test_the_lease_stays_while_a_turn_the_closed_page_started_is_still_running(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_blocking_claude(
        monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Done.")
    )
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}, timeout=WAIT) as page:
        page_events = events_of(page)  # kept: dropping the iterator would close the stream
        next(page_events)
        with api.stream(
            "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "Go on."}, timeout=WAIT
        ) as reply:
            replies = events_of(reply)
            assert next(replies)["type"] == "RUN_STARTED"
            assert fake.started.wait(WAIT)

            page.close()
            time.sleep(0.6)  # long enough for the server to see the page go

            assert holder(pipeline) == "tab:t1", "the agent is still editing the worktree"

            fake.release.set()
            list(replies)

    assert until(lambda: holder(pipeline) is None), "released once the turn has ended"


# --- one turn at a time on a session ------------------------------------------------------------


def test_a_second_turn_on_a_session_is_refused_while_the_first_runs(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_blocking_claude(
        monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Done.")
    )
    with api.stream(
        "POST", f"{REVIEW}/chat", json={"tab": "t1", "prompt": "First."}, timeout=WAIT
    ) as reply:
        replies = events_of(reply)
        next(replies)
        assert fake.started.wait(WAIT)

        same_tab = api.post(f"{REVIEW}/chat", json={"tab": "t1", "prompt": "Second."})
        other_tab = api.post(f"{REVIEW}/chat", json={"tab": "t2", "prompt": "Second."})

        fake.release.set()
        list(replies)

    assert same_tab.status_code == 409 and other_tab.status_code == 409
    assert len(fake.calls) == 1


def test_two_tabs_cannot_both_continue_an_idle_claude_session(
    pipeline: Installation, tmp_path: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.settings import settings

    project = tmp_path / "project"
    project.mkdir()
    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, OTHER_SESSION, project)
    fake = use_blocking_claude(monkeypatch, finished_build(project, "Done."))
    url = f"/api/sessions/claude_code/{OTHER_SESSION}/continue"
    with api.stream("POST", url, json={"tab": "t1", "prompt": "A."}, timeout=WAIT) as reply:
        replies = events_of(reply)
        next(replies)
        assert fake.started.wait(WAIT)

        second = api.post(url, json={"tab": "t2", "prompt": "B."})

        fake.release.set()
        list(replies)

    assert second.status_code == 409
    assert len(fake.calls) == 1


def test_a_session_started_here_is_read_only_to_a_process_that_later_holds_it(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    use_agent(tmp_path / "agent.jsonl")
    turn(
        api,
        "/api/sessions",
        {
            "tab": "t1",
            "runtime": "acp",
            "model": "deep-2",
            "unit": "feature/2",
            "prompt": "Look around.",
        },
    )

    with holding_process(ACP_SESSION):
        opened = api.get(f"/api/sessions/acp/{ACP_SESSION}").json()

    assert opened["read_only"] is True
    assert "process" in opened["reason"].lower()


def test_an_unknown_runtime_is_refused_before_a_lease_is_taken(
    pipeline: Installation, api: httpx.Client
) -> None:
    reply = api.post(
        "/api/sessions",
        json={"tab": "t1", "runtime": "nope", "unit": "feature/2", "prompt": "Hi."},
    )

    assert reply.status_code == 400
    assert holder(pipeline) is None


def test_a_step_that_took_the_branch_after_the_check_is_met_by_the_lease_first(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unit looks idle in the store, but a step holds its branch: the lease is taken first
    and the check made again, so the turn is refused and the lease given back."""
    fake = use_claude(monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Hi."))

    with branch_lock("spec/feature/2", root=pipeline.state_dir / "locks"):
        reply = api.post(f"{REVIEW}/chat", json={"tab": "t1", "prompt": "Hi."})

    assert reply.status_code == 409
    assert holder(pipeline) is None
    assert fake.calls == []


# --- the model the session ran on --------------------------------------------------------------


def test_a_turn_runs_on_the_model_the_session_recorded(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Hi."))

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Hi."})

    argv = fake.calls[0][0]
    assert argv[argv.index("--model") + 1] == "opus"


# --- a session in a unit's worktree is the unit's ----------------------------------------------


def test_a_session_in_the_worktree_of_a_running_unit_cannot_be_continued_in_place(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.settings import settings

    tree = unit_worktree(pipeline, "feature/7")
    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, OTHER_SESSION, tree)
    fake = use_claude(monkeypatch, finished_build(tree, "Hi."))

    reply = api.post(
        f"/api/sessions/claude_code/{OTHER_SESSION}/continue", json={"tab": "t1", "prompt": "Hi."}
    )

    assert reply.status_code == 409
    assert fake.calls == []


def test_a_session_in_a_units_worktree_goes_under_its_lease_and_the_pipelines_policy(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.settings import settings

    tree = unit_worktree(pipeline, "feature/2")
    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, OTHER_SESSION, tree)
    fake = use_claude(monkeypatch, finished_build(tree, "Hi."))

    turn(api, f"/api/sessions/claude_code/{OTHER_SESSION}/continue", {"tab": "t1", "prompt": "Hi."})

    argv = fake.calls[0][0]
    assert holder(pipeline) == "tab:t1"
    assert "hooks" in json.loads(argv[argv.index("--settings") + 1])


def test_a_claude_working_in_a_directory_holds_its_newest_session_without_naming_it(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    from agent_build_kit.settings import settings

    project = tmp_path / "project"
    project.mkdir()
    assert settings.claude_home is not None
    older = claude_session_file(settings.claude_home, OTHER_SESSION, project)
    newer = claude_session_file(settings.claude_home, BUILD_SESSION, project)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_100, 1_700_000_100))

    with claude_working_in(project):
        opened = api.get(f"/api/sessions/claude_code/{BUILD_SESSION}").json()
        listed = {s["id"]: s for s in api.get("/api/sessions").json()["sessions"]}

    assert opened["read_only"] is True
    assert "process" in opened["reason"].lower()
    assert listed[BUILD_SESSION]["held"] is True
    assert listed[OTHER_SESSION]["held"] is False


# --- the live stream ----------------------------------------------------------------------------


def test_a_new_step_is_streamed_whole_even_when_an_old_run_is_removed_as_it_opens(
    pipeline: Installation,
) -> None:
    from agent_build_kit.serve.server import start_server

    directory = transcript_dir(pipeline.state_dir)
    first = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)

    def run(started: datetime) -> Transcript:
        return Transcript(
            directory,
            unit("feature/7", change="feature"),
            node="implement",
            round=0,
            started=started,
            result_limit=1000,
            runs_kept=1,
        )

    old = run(first)
    for word in ("one", "two", "three"):
        old.record(TranscriptEvent(kind="text", session="s", text=word))
    old.record(TranscriptEvent(kind="stop", session="s", text="end_turn"))

    with start_server(pipeline) as server, httpx.Client(base_url=server.url) as api:
        with api.stream(
            "GET", "/api/units/feature/7/agent/events", params={"tab": "t1"}, timeout=WAIT
        ) as stream:
            events = events_of(stream)
            assert next(events)["type"] == "MESSAGES_SNAPSHOT"

            new = run(first + timedelta(minutes=5))  # removes the old run's file
            new.record(TranscriptEvent(kind="text", session="s", text="alpha "))
            new.record(TranscriptEvent(kind="text", session="s", text="beta"))
            new.record(TranscriptEvent(kind="stop", session="s", text="end_turn"))

            seen = []
            for event in events:
                seen.append(event)
                if event["type"] == "RUN_FINISHED":
                    break

    validate_stream(seen)
    assert seen[0]["type"] == "RUN_STARTED"
    assert "".join(e.get("delta", "") for e in seen) == "alpha beta"


def test_the_live_stream_opens_each_run_and_follows_the_protocols_order(
    pipeline: Installation,
) -> None:
    from agent_build_kit.serve.server import start_server

    directory = transcript_dir(pipeline.state_dir)
    with start_server(pipeline) as server, httpx.Client(base_url=server.url) as api:
        with api.stream(
            "GET", "/api/units/feature/7/agent/events", params={"tab": "t1"}, timeout=WAIT
        ) as stream:
            events = events_of(stream)
            snapshot = next(events)
            for number, started in enumerate((0, 5)):
                step = Transcript(
                    directory,
                    unit("feature/7", change="feature"),
                    node="implement",
                    round=number,
                    started=datetime(2026, 10, 1, 9, started, 0, tzinfo=UTC),
                    result_limit=1000,
                    runs_kept=3,
                )
                step.record(TranscriptEvent(kind="text", session="s", text="Working."))
                step.record(TranscriptEvent(kind="stop", session="s", text="end_turn"))
            seen = []
            for event in events:
                seen.append(event)
                if sum(e["type"] == "RUN_FINISHED" for e in seen) == 2:
                    break

    validate_stream([snapshot, *seen])
    assert [e["type"] for e in seen].count("RUN_STARTED") == 2


# --- what was asked is part of the history ------------------------------------------------------


def test_the_history_holds_the_question_before_the_answer(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_claude(monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Because."))

    reply = turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Why this approach?"})
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t2"}, timeout=WAIT) as stream:
        snapshot = next(events_of(stream))

    validate_stream(reply)
    assert reply[0]["type"] == "RUN_STARTED"
    roles = [m["role"] for m in snapshot["messages"]]
    assert roles[0] == "user" and "assistant" in roles[1:]
    assert "Why this approach?" in snapshot["messages"][0]["content"]
    assert snapshot["messages"][-1]["content"] == "Because."


def test_a_turns_attachments_are_in_the_question_the_history_keeps(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Ok."))
    attachment = {"file": "src/a.py", "lines": [1, 2], "hunk": "@@ -1 +1 @@", "text": "x = 1"}

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "This?", "attachments": [attachment]})
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t2"}, timeout=WAIT) as stream:
        snapshot = next(events_of(stream))

    assert snapshot["messages"][0]["content"] == prompt_of(fake.calls[0][0])


# --- a page that is not a unit's agent tab is a tab all the same --------------------------------


def test_a_sessions_page_closing_returns_the_unit_its_turn_took(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    step = Transcript(
        transcript_dir(pipeline.state_dir),
        unit("feature/2", change="feature"),
        node="implement",
        round=0,
        started=datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC),
        result_limit=1000,
        runs_kept=3,
    )
    step.record(TranscriptEvent(kind="text", session=ACP_SESSION, text="Earlier."))
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=(ACP_SESSION,))

    with api.stream("GET", "/api/tabs/events", params={"tab": "t1"}, timeout=WAIT) as page:
        lines = page.iter_lines()  # kept: dropping the iterator would close the stream
        next(lines)
        turn(api, f"/api/sessions/acp/{ACP_SESSION}/continue", {"tab": "t1", "prompt": "On."})
        assert holder(pipeline) == "tab:t1"

    assert until(lambda: holder(pipeline) is None)


def test_a_permission_request_on_a_session_of_no_unit_is_denied_when_its_page_closes(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    pipeline.checkouts["app"].mkdir(parents=True, exist_ok=True)
    record = tmp_path / "agent.jsonl"
    use_agent(record, act=[{"ask": "execute", "command": "ls src"}])

    with api.stream("GET", "/api/tabs/events", params={"tab": "t1"}, timeout=WAIT) as page:
        lines = page.iter_lines()
        next(lines)
        with api.stream(
            "POST",
            "/api/sessions",
            json={"tab": "t1", "runtime": "acp", "repo": "app", "prompt": "List it."},
            timeout=WAIT,
        ) as reply:
            replies = events_of(reply)
            for event in replies:
                if event["type"] == "CUSTOM" and event["name"] == "permission_request":
                    break
            else:
                raise AssertionError("the turn never asked for permission")

            page.close()

            assert until(lambda: requests(record, "did/ask"))
            list(replies)

    [asked] = requests(record, "did/ask")
    assert asked["outcome"] == "cancelled" or str(asked["optionKind"]).startswith("reject")
    assert requests(record, "did/run") == []
