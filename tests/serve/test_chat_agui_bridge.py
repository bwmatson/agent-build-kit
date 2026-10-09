"""The bridge maps what both runtimes record to AG-UI events.

The agents are faked at their wire: a Claude run is the CLI's stream-json lines, an ACP
run is a real agent process speaking the protocol. What reaches the encoder is what the
runtimes record from them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.claude_stream import records
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.serve.bridge import AgUiEncoder, messages_snapshot
from tests.agui_protocol import validate_stream
from tests.runtimes.acp_agent import ANSWER, THOUGHT, TOOL_TITLE, use_agent
from tests.runtimes.claude_cli import finished_build


def encoded(events: list[TranscriptEvent]) -> list[dict[str, Any]]:
    encoder = AgUiEncoder()
    out = [made for event in events for made in encoder.encode(event)]
    return out + encoder.close()


def types(events: list[dict[str, Any]]) -> list[str]:
    """The event types, a run of the same type counted once (a message is many deltas)."""
    out: list[str] = []
    for event in events:
        if not out or out[-1] != event["type"]:
            out.append(event["type"])
    return out


def said(events: list[dict[str, Any]], kind: str) -> str:
    return "".join(e["delta"] for e in events if e["type"] == f"{kind}_MESSAGE_CONTENT")


def claude_events(stdout: str) -> list[TranscriptEvent]:
    return [made for line in stdout.splitlines() for made in records(json.loads(line))]


def acp_events(tmp_path: Path, **agent: Any) -> list[TranscriptEvent]:
    work = tmp_path / "work"
    work.mkdir()
    use_agent(tmp_path / "agent.jsonl", **agent)
    seen: list[TranscriptEvent] = []
    AcpRuntime().run(AgentRequest(prompt="Go.", role="implement", cwd=work, on_record=seen.append))
    return seen


def test_a_claude_run_maps_text_tool_calls_results_usage_and_the_stop(tmp_path: Path) -> None:
    out = encoded(claude_events(finished_build(tmp_path, "All done.")))

    assert types(out) == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "CUSTOM",
        "RUN_FINISHED",
    ]
    start = next(e for e in out if e["type"] == "TOOL_CALL_START")
    result = next(e for e in out if e["type"] == "TOOL_CALL_RESULT")
    assert start["toolCallName"] == "Edit"
    assert result["toolCallId"] == start["toolCallId"] == "toolu_01AbCdEfGhJkLmNpQrStUvWx"
    assert "has been updated" in result["content"]
    args = json.loads(next(e for e in out if e["type"] == "TOOL_CALL_ARGS")["delta"])
    assert args["old_string"] == "MARKER = None"
    usage = next(e for e in out if e["type"] == "CUSTOM")
    assert usage["name"] == "usage" and usage["value"]["output_tokens"] == 212
    assert out[-1]["result"] == {"stopReason": "success"}


def test_each_message_has_its_own_id_that_its_deltas_repeat(tmp_path: Path) -> None:
    out = encoded(claude_events(finished_build(tmp_path, "All done.")))

    starts = [e["messageId"] for e in out if e["type"] == "TEXT_MESSAGE_START"]
    contents = [e["messageId"] for e in out if e["type"] == "TEXT_MESSAGE_CONTENT"]
    assert len(set(starts)) == 2
    assert contents == starts


def test_claude_reasoning_is_its_own_message_kind() -> None:
    thinking = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "The marker goes in app.py."}],
        },
        "session_id": "7c2e4290-1d5a-4b8f-a429-3e6f0b1c9d72",
    }

    out = encoded(claude_events(json.dumps(thinking)))

    assert types(out) == [
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_END",
    ]
    assert said(out, "REASONING") == "The marker goes in app.py."


def test_a_claude_error_result_is_a_run_error() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "subtype": "error_max_turns",
            "is_error": True,
            "num_turns": 30,
            "errors": ["out of turns"],
            "session_id": "7c2e4290-1d5a-4b8f-a429-3e6f0b1c9d72",
        }
    )

    out = encoded(claude_events(stdout))

    assert out[-1]["type"] == "RUN_ERROR"
    assert "error_max_turns" in out[-1]["message"]


def test_an_acp_run_maps_thoughts_text_tool_calls_and_the_stop(tmp_path: Path) -> None:
    out = encoded(acp_events(tmp_path))

    kinds = types(out)
    assert kinds[0] == "REASONING_MESSAGE_START"
    assert said(out, "REASONING") == THOUGHT
    start = next(e for e in out if e["type"] == "TOOL_CALL_START")
    assert start["toolCallName"] == TOOL_TITLE
    result = next(e for e in out if e["type"] == "TOOL_CALL_RESULT")
    assert result["toolCallId"] == start["toolCallId"]
    assert "Updated src/app.py" in result["content"]
    assert said(out, "TEXT").endswith(ANSWER)
    assert kinds[-1] == "RUN_FINISHED"
    assert out[-1]["result"] == {"stopReason": "end_turn"}


def test_an_acp_plan_update_is_a_plan_event(tmp_path: Path) -> None:
    out = encoded(acp_events(tmp_path, act=[{"plan": [["Add the marker", "in_progress"]]}]))

    plan = next(e for e in out if e["type"] == "CUSTOM" and e["name"] == "plan")
    assert "Add the marker" in plan["value"]


def test_an_acp_stop_reason_other_than_end_of_turn_is_carried(tmp_path: Path) -> None:
    out = encoded(acp_events(tmp_path, stop="max_tokens"))

    assert out[-1]["type"] == "RUN_FINISHED"
    assert out[-1]["result"] == {"stopReason": "max_tokens"}


def test_an_unfinished_message_is_closed_when_the_run_is_cut_short() -> None:
    out = encoded([TranscriptEvent(kind="text", text="Starting")])

    assert types(out) == ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]


def test_a_loaded_history_maps_to_a_messages_snapshot(tmp_path: Path) -> None:
    history = claude_events(finished_build(tmp_path, "All done."))

    snapshot = messages_snapshot(history)

    assert snapshot["type"] == "MESSAGES_SNAPSHOT"
    messages = snapshot["messages"]
    assert [m["role"] for m in messages if m["role"] == "tool"] == ["tool"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert "I'll add the marker to the app module." in assistant[0]["content"]
    calls = [call for m in assistant for call in m.get("toolCalls", [])]
    assert [(c["id"], c["type"], c["function"]["name"]) for c in calls] == [
        ("toolu_01AbCdEfGhJkLmNpQrStUvWx", "function", "Edit")
    ]
    assert json.loads(calls[0]["function"]["arguments"])["old_string"] == "MARKER = None"
    tool = next(m for m in messages if m["role"] == "tool")
    assert tool["toolCallId"] == "toolu_01AbCdEfGhJkLmNpQrStUvWx"
    assert "has been updated" in tool["content"]
    assert assistant[-1]["content"] == "All done."


def run_of(events: list[TranscriptEvent]) -> list[dict[str, Any]]:
    """What a turn streams: the run opened, every event, whatever was left open."""
    encoder = AgUiEncoder("thread-1", "run-1")
    out = encoder.start()
    for event in events:
        out += encoder.encode(event)
    return out + encoder.close()


def test_a_claude_run_is_a_run_the_protocols_own_models_accept(tmp_path: Path) -> None:
    out = run_of(claude_events(finished_build(tmp_path, "All done.")))

    validate_stream(out)
    assert out[0] == {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"}
    assert out[-1]["threadId"] == "thread-1" and out[-1]["runId"] == "run-1"


def test_an_acp_run_is_a_run_the_protocols_own_models_accept(tmp_path: Path) -> None:
    validate_stream(run_of(acp_events(tmp_path)))


def test_a_run_that_fails_is_one_run_with_one_error() -> None:
    encoder = AgUiEncoder("thread-1", "run-1")
    out = encoder.start()
    out += encoder.encode(TranscriptEvent(kind="text", text="Starting"))
    out += encoder.fail("the agent went away")

    validate_stream(out)
    assert [e["type"] for e in out][-2:] == ["TEXT_MESSAGE_END", "RUN_ERROR"]
    assert out[-1]["runId"] == "run-1"


def test_two_runs_one_after_the_other_are_a_valid_stream(tmp_path: Path) -> None:
    first = run_of(claude_events(finished_build(tmp_path, "One.")))
    second = AgUiEncoder("thread-1", "run-2")
    out = [{"type": "MESSAGES_SNAPSHOT", "messages": []}, *first, *second.start()]
    out += second.fail("cut short")

    validate_stream(out)


def test_a_history_is_a_snapshot_the_protocols_models_accept(tmp_path: Path) -> None:
    history = [
        TranscriptEvent(kind="user", text="Why this approach?"),
        *claude_events(finished_build(tmp_path, "Because.")),
    ]

    snapshot = messages_snapshot(history)

    validate_stream([snapshot])
    assert [m["role"] for m in snapshot["messages"]][:2] == ["user", "assistant"]
    assert snapshot["messages"][0]["content"] == "Why this approach?"


def test_a_history_with_no_events_is_an_empty_snapshot() -> None:
    assert messages_snapshot([]) == {"type": "MESSAGES_SNAPSHOT", "messages": []}
