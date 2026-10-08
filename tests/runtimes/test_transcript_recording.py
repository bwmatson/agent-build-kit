"""What each runtime hands the unit's transcript, in one shape for both.

The `claude` process is faked at its stream-json boundary (tests/runtimes/claude_cli.py)
and the ACP agent is a real subprocess over stdio (tests/runtimes/acp_agent.py), so the
runtimes see what the real ones send. The transcript is a real one on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path

import pytest

from agent_build_kit.pipeline.transcript import (
    Transcript,
    TranscriptEvent,
    read_transcripts,
    transcript_dir,
)
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.factories import unit
from tests.runtimes import claude_cli
from tests.runtimes.acp_agent import ANSWER, PREAMBLE, THOUGHT, TOOL_TITLE, use_agent
from tests.runtimes.acp_agent import SESSION as ACP_SESSION
from tests.runtimes.claude_cli import FakeClaude, finished_build, stream

START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)
CLAUDE_CALL = "toolu_01AbCdEfGhJkLmNpQrStUvWx"


def transcript_for(tmp_path: Path, *, result_limit: int = 20000) -> Transcript:
    return Transcript(
        transcript_dir(tmp_path / "state"),
        unit("add-marker/1", change="add-marker"),
        node="implement",
        round=2,
        started=START,
        result_limit=result_limit,
        runs_kept=3,
    )


def request(cwd: Path, transcript: Transcript, **fields: object) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        on_record=transcript.record,
        **fields,  # pyrefly: ignore
    )


def recorded(tmp_path: Path) -> list[TranscriptEvent]:
    return read_transcripts(transcript_dir(tmp_path / "state"), "add-marker/1")


def kinds(events: list[TranscriptEvent]) -> list[str]:
    """The kinds in order, a run of one kind (an agent's reply in chunks) counted once."""
    return [kind for kind, _ in groupby(e.kind for e in events)]


def assistant(*content: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_01Hq7ZkP3xYwVb2nR8tLcD4e",
            "type": "message",
            "role": "assistant",
            "model": claude_cli.MODEL,
            "content": list(content),
            "stop_reason": None,
            "stop_sequence": None,
            "usage": claude_cli.USAGE,  # the recorded stream's own usage block
            "context_management": None,
        },
        "parent_tool_use_id": None,
        "session_id": claude_cli.SESSION,
        "uuid": "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e47",
    }


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    (path / "src").mkdir(parents=True)
    (path / "src" / "app.py").write_text("MARKER = None\n")
    return path


def run_claude(worktree: Path, tmp_path: Path, stdout: str, **limits: int) -> None:
    ClaudeCodeRuntime(execute=FakeClaude(stdout=stdout)).run(
        request(worktree, transcript_for(tmp_path, **limits))
    )


def run_acp(worktree: Path, tmp_path: Path, **agent: object) -> None:
    use_agent(tmp_path / "agent.jsonl", **agent)  # pyrefly: ignore
    AcpRuntime().run(request(worktree, transcript_for(tmp_path)))


def test_a_claude_steps_events_are_recorded_in_order_with_the_session(
    worktree: Path, tmp_path: Path
) -> None:
    run_claude(worktree, tmp_path, finished_build(worktree, "Added the marker."))

    events = recorded(tmp_path)

    assert [k for k in kinds(events) if k != "usage"] == [
        "text",
        "tool_call",
        "tool_result",
        "text",
        "stop",
    ]
    assert {e.session for e in events} == {claude_cli.SESSION}
    assert [e.text for e in events if e.kind == "text"] == [
        "I'll add the marker to the app module.",
        "Added the marker.",
    ]


def test_a_claude_tool_call_and_its_result_are_recorded_whole_and_paired(
    worktree: Path, tmp_path: Path
) -> None:
    run_claude(worktree, tmp_path, finished_build(worktree, "Added the marker."))

    events = recorded(tmp_path)
    (tool_call,) = [e for e in events if e.kind == "tool_call"]
    (tool_result,) = [e for e in events if e.kind == "tool_result"]

    assert tool_call.tool == "Edit"
    assert tool_call.call == CLAUDE_CALL
    assert tool_call.input["old_string"] == "MARKER = None"
    assert tool_call.input["new_string"] == 'MARKER = "added"'
    assert tool_result.call == CLAUDE_CALL
    assert "has been updated" in tool_result.text


def test_a_claude_steps_usage_and_stop_are_recorded(worktree: Path, tmp_path: Path) -> None:
    run_claude(worktree, tmp_path, finished_build(worktree, "Added the marker."))

    events = recorded(tmp_path)

    assert any(
        e.kind == "usage" and e.usage["output_tokens"] == 212 and e.usage["input_tokens"] == 4
        for e in events
    )
    assert [e.kind for e in events][-1] == "stop"
    assert events[-1].text, "the stop says why the turn ended"


def test_a_claude_steps_reasoning_is_recorded(worktree: Path, tmp_path: Path) -> None:
    opening = finished_build(worktree, "done").splitlines()[0]
    thinking = assistant(
        {
            "type": "thinking",
            "thinking": "The marker belongs beside the other constants.",
            "signature": "EpoDCkYICxgCKkB0aGlzIGlzIG5vdCBhIHJlYWwgc2lnbmF0dXJl",
        }
    )

    run_claude(worktree, tmp_path, opening + "\n" + stream(thinking))

    (reasoning,) = [e for e in recorded(tmp_path) if e.kind == "reasoning"]
    assert reasoning.text == "The marker belongs beside the other constants."
    assert reasoning.session == claude_cli.SESSION


def test_every_event_carries_the_context_the_transcript_was_opened_with(
    worktree: Path, tmp_path: Path
) -> None:
    run_claude(worktree, tmp_path, finished_build(worktree, "Added the marker."))

    events = recorded(tmp_path)

    assert {(e.unit, e.node, e.round, e.source) for e in events} == {
        ("add-marker/1", "implement", 2, "build")
    }
    stamps = [datetime.fromisoformat(e.at) for e in events]
    assert stamps == sorted(stamps)
    assert all(stamp.tzinfo is not None for stamp in stamps)


def test_an_event_is_in_the_file_before_the_next_one_arrives(
    worktree: Path, tmp_path: Path
) -> None:
    transcript = transcript_for(tmp_path)
    lengths: list[int] = []

    def record(event: TranscriptEvent) -> None:
        transcript.record(event)
        lengths.append(len(transcript.path.read_text().splitlines()))

    ClaudeCodeRuntime(execute=FakeClaude(stdout=finished_build(worktree, "done"))).run(
        AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, on_record=record)
    )

    assert lengths == list(range(1, len(lengths) + 1))
    assert len(lengths) >= 5


def test_a_long_claude_tool_result_is_cut_at_the_configured_size(
    worktree: Path, tmp_path: Path
) -> None:
    run_claude(worktree, tmp_path, finished_build(worktree, "done"), result_limit=10)

    (tool_result,) = [e for e in recorded(tmp_path) if e.kind == "tool_result"]

    assert tool_result.truncated is not None and tool_result.truncated > 10
    assert str(tool_result.truncated) in tool_result.text[10:]


def test_an_acp_steps_events_are_recorded_in_order_with_the_session(
    worktree: Path, tmp_path: Path
) -> None:
    run_acp(worktree, tmp_path, usage="reported")

    events = recorded(tmp_path)

    assert kinds(events) == [
        "reasoning",
        "text",
        "tool_call",
        "tool_result",
        "text",
        "usage",
        "stop",
    ]
    assert {e.session for e in events} == {ACP_SESSION}
    assert "".join(e.text for e in events if e.kind == "reasoning") == THOUGHT
    texts = [
        "".join(e.text for e in group).strip()
        for is_text, group in groupby(events, key=lambda e: e.kind == "text")
        if is_text
        for group in [list(group)]
    ]
    assert texts == [PREAMBLE, ANSWER]


def test_an_acp_tool_call_and_its_result_are_recorded_though_the_session_would_not_replay_them(
    worktree: Path, tmp_path: Path
) -> None:
    run_acp(worktree, tmp_path)

    events = recorded(tmp_path)
    (tool_call,) = [e for e in events if e.kind == "tool_call"]
    (tool_result,) = [e for e in events if e.kind == "tool_result"]

    assert tool_call.tool == TOOL_TITLE
    assert tool_call.call == "call_01"
    assert tool_call.input["old"] == "MARKER = None"
    assert tool_result.call == "call_01"
    assert "Updated src/app.py" in tool_result.text


def test_an_acp_steps_usage_and_stop_are_recorded(worktree: Path, tmp_path: Path) -> None:
    run_acp(worktree, tmp_path, usage="reported")

    events = recorded(tmp_path)

    assert any(
        e.kind == "usage" and e.usage["input_tokens"] == 7000 and e.usage["output_tokens"] == 1500
        for e in events
    )
    assert (events[-1].kind, events[-1].text) == ("stop", "end_turn")


def test_both_runtimes_write_the_same_fields_for_the_same_kind_of_event(
    worktree: Path, tmp_path: Path
) -> None:
    claude_dir, acp_dir = tmp_path / "claude", tmp_path / "acp"
    claude_dir.mkdir()
    acp_dir.mkdir()
    run_claude(worktree, claude_dir, finished_build(worktree, "done"))
    run_acp(worktree, acp_dir, usage="reported")

    def filled_by_kind(root: Path) -> tuple[dict[str, set[str]], set[str]]:
        """Per kind, the fields a runtime filled in; and the keys of its usage counts."""
        found: dict[str, set[str]] = {}
        usage_keys: set[str] = set()
        for path in transcript_dir(root / "state").iterdir():
            for line in path.read_text().splitlines():
                event = TranscriptEvent.model_validate_json(line)
                found.setdefault(event.kind, set()).update(event.model_dump(exclude_defaults=True))
                usage_keys.update(event.usage)
        return found, usage_keys

    claude_filled, claude_usage = filled_by_kind(claude_dir)
    acp_filled, acp_usage = filled_by_kind(acp_dir)
    for kind in ("text", "tool_call", "tool_result", "usage", "stop"):
        assert claude_filled[kind] == acp_filled[kind], kind
    assert claude_filled["tool_call"] >= {"tool", "call", "input"}
    assert claude_filled["tool_result"] >= {"call", "text"}
    assert claude_usage == acp_usage
