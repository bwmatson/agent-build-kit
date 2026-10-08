"""A unit's transcript: what is written, how it is bounded, and how it is read back.

One file per run or chat turn, one event per line, appended as events arrive.
The runtimes feed it (tests/runtimes/test_transcript_recording.py); here the
events are handed to it directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.transcript import (
    SessionHistory,
    Transcript,
    TranscriptEvent,
    read_transcripts,
    remove_change_transcripts,
    replay,
    transcript_dir,
)
from tests.factories import stored_unit, unit
from tests.pipeline.test_archive import FakeRunner

START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)
SESSION = "3f1c2a9e-5b7d-4e2f-9a61-0c8d7e4b2a15"


class Clock:
    """A clock that moves a second on each reading."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def open_transcript(
    directory: Path,
    uid: str = "add-marker/1",
    *,
    at: datetime = START,
    node: str = "implement",
    round: int = 1,
    source: str = "build",
    result_limit: int = 20000,
    runs_kept: int = 3,
) -> Transcript:
    return Transcript(
        directory,
        unit(uid, change=uid.split("/")[0]),
        node=node,
        round=round,
        source=source,  # pyrefly: ignore
        started=at,
        result_limit=result_limit,
        runs_kept=runs_kept,
        clock=Clock(at),
    )


def said(text: str, kind: str = "text") -> TranscriptEvent:
    return TranscriptEvent(kind=kind, text=text, session=SESSION)  # pyrefly: ignore


def result(text: str, call: str = "toolu_01") -> TranscriptEvent:
    return TranscriptEvent(kind="tool_result", text=text, call=call, session=SESSION)


def call(tool: str = "Bash", call: str = "toolu_01", **input: object) -> TranscriptEvent:
    return TranscriptEvent(kind="tool_call", tool=tool, call=call, input=input, session=SESSION)


def test_an_event_carries_the_time_unit_node_round_session_and_source_it_was_recorded_with(
    tmp_path: Path,
) -> None:
    directory = transcript_dir(tmp_path)
    transcript = open_transcript(directory, node="rework", round=2)

    transcript.record(said("Adding the marker."))

    (event,) = read_transcripts(directory, "add-marker/1")
    assert (event.unit, event.node, event.round) == ("add-marker/1", "rework", 2)
    assert (event.session, event.source, event.kind) == (SESSION, "build", "text")
    assert datetime.fromisoformat(event.at) > START


def test_each_event_is_one_json_line_written_when_it_arrives(tmp_path: Path) -> None:
    transcript = open_transcript(transcript_dir(tmp_path))

    for n in range(1, 4):
        transcript.record(said(f"step {n}"))
        lines = transcript.path.read_text().splitlines()
        assert [json.loads(line)["text"] for line in lines] == [
            f"step {i}" for i in range(1, n + 1)
        ]


def test_a_tool_result_over_the_size_is_cut_with_a_marker_giving_its_original_length(
    tmp_path: Path,
) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, result_limit=100).record(result("x" * 500))

    (event,) = read_transcripts(directory, "add-marker/1")

    assert event.text.startswith("x" * 100)
    assert not event.text.startswith("x" * 101)
    assert "500" in event.text[100:], "the marker says how long the result was"
    assert event.truncated == 500


def test_a_tool_result_at_the_size_is_kept_whole(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, result_limit=100).record(result("x" * 100))

    (event,) = read_transcripts(directory, "add-marker/1")

    assert event.text == "x" * 100
    assert event.truncated is None


def test_only_a_tool_result_is_cut(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    transcript = open_transcript(directory, result_limit=100)
    long = "y" * 500

    transcript.record(said(long))
    transcript.record(said(long, "reasoning"))
    transcript.record(call(command=long))

    events = read_transcripts(directory, "add-marker/1")
    assert [e.text for e in events[:2]] == [long, long]
    assert events[2].input == {"command": long}
    assert all(e.truncated is None for e in events)


def test_a_chat_turn_is_recorded_as_chat_in_the_same_sequence_as_the_builds(
    tmp_path: Path,
) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, at=START).record(said("Built it."))
    open_transcript(
        directory, at=START + timedelta(hours=1), node="chat", round=0, source="chat"
    ).record(said("Why a marker?"))
    open_transcript(directory, at=START + timedelta(hours=2), node="rework", round=1).record(
        said("Reworked.")
    )

    events = read_transcripts(directory, "add-marker/1")

    assert [(e.source, e.node, e.text) for e in events] == [
        ("build", "implement", "Built it."),
        ("chat", "chat", "Why a marker?"),
        ("build", "rework", "Reworked."),
    ]


def test_a_units_transcript_holds_only_its_own_events(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, "add-marker/1").record(said("one"))
    open_transcript(directory, "add-marker/10").record(said("ten"))
    open_transcript(directory, "other-change/1").record(said("other"))

    assert [e.text for e in read_transcripts(directory, "add-marker/1")] == ["one"]


def test_only_the_most_recent_runs_of_a_unit_are_kept(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    runs = []
    for n in range(2):
        runs.append(open_transcript(directory, at=START + timedelta(hours=n), runs_kept=2))
        runs[-1].record(said(f"run {n}"))
    neighbour = open_transcript(directory, "add-marker/10", at=START)
    neighbour.record(said("another unit"))

    third = open_transcript(directory, at=START + timedelta(hours=2), runs_kept=2)

    assert not runs[0].path.exists(), "the oldest goes when a new run starts"
    assert runs[1].path.exists()
    assert neighbour.path.exists()
    third.record(said("run 2"))
    assert [e.text for e in read_transcripts(directory, "add-marker/1")] == ["run 1", "run 2"]


def test_removing_a_changes_transcripts_leaves_other_changes_alone(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, "add-marker/1").record(said("one"))
    open_transcript(directory, "add-marker/12").record(said("twelve"))
    kept = open_transcript(directory, "add-marker-extra/1")
    kept.record(said("other"))

    remove_change_transcripts(directory, "add-marker")

    assert [p.name for p in directory.iterdir()] == [kept.path.name]


def test_archiving_a_change_removes_its_units_transcripts(tmp_path: Path) -> None:
    (tmp_path / "openspec" / "changes" / "add-marker").mkdir(parents=True)
    directory = transcript_dir(tmp_path)
    open_transcript(directory, "add-marker/1").record(said("one"))
    open_transcript(directory, "add-marker/2").record(said("two"))
    units = [
        stored_unit("add-marker/1", state="merged"),
        stored_unit("add-marker/2", state="merged"),
    ]

    archived = archive_ready_changes(
        units, planning_repo=tmp_path, run=FakeRunner(), transcripts=directory
    )

    assert archived == ["add-marker"]
    assert list(directory.iterdir()) == []


def test_a_change_not_archived_keeps_its_transcripts(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    open_transcript(directory, "add-marker/1").record(said("one"))
    units = [
        stored_unit("add-marker/1", state="merged"),
        stored_unit("add-marker/2", state="in_review"),
    ]

    archive_ready_changes(units, planning_repo=tmp_path, run=FakeRunner(), transcripts=directory)

    assert len(list(directory.iterdir())) == 1


def no_history(session: str) -> SessionHistory:
    raise AssertionError(f"the runtime was asked for {session}, which was recorded")


def test_the_replay_is_the_builds_and_the_chat_turns_in_order_tool_calls_included(
    tmp_path: Path,
) -> None:
    directory = transcript_dir(tmp_path)
    build = open_transcript(directory, at=START)
    build.record(said("Running the tests."))
    build.record(call("Bash", "toolu_01", command="uv run pytest"))
    build.record(result("3 passed", "toolu_01"))
    chat = open_transcript(directory, at=START + timedelta(hours=1), node="chat", source="chat")
    chat.record(said("Did they pass?"))
    chat.record(said("Yes, three."))

    shown = replay(directory, "add-marker/1", SESSION, runtime_history=no_history)

    assert [(e.kind, e.source) for e in shown.events] == [
        ("text", "build"),
        ("tool_call", "build"),
        ("tool_result", "build"),
        ("text", "chat"),
        ("text", "chat"),
    ]
    assert shown.events[1].input == {"command": "uv run pytest"}
    assert shown.events[2].text == "3 passed"
    assert shown.recorded is True
    assert shown.tool_calls_available is True


def test_a_session_that_was_not_recorded_is_read_from_the_runtimes_own_history(
    tmp_path: Path,
) -> None:
    editor_session = "sess_Ln3Vt8QaRcXe5mJd"
    asked: list[str] = []

    def history(session: str) -> SessionHistory:
        asked.append(session)
        return SessionHistory(
            events=(said("Refactor the parser."), said("Done.")), tool_calls=False
        )

    shown = replay(
        transcript_dir(tmp_path), "add-marker/1", editor_session, runtime_history=history
    )

    assert asked == [editor_session]
    assert [e.text for e in shown.events] == ["Refactor the parser.", "Done."]
    assert shown.recorded is False
    assert shown.tool_calls_available is False


def test_a_runtime_that_keeps_tool_calls_is_not_reported_as_missing_them(tmp_path: Path) -> None:
    def history(session: str) -> SessionHistory:
        return SessionHistory(events=(call(command="ls"),), tool_calls=True)

    shown = replay(transcript_dir(tmp_path), "add-marker/1", "sess_other", runtime_history=history)

    assert shown.recorded is False
    assert shown.tool_calls_available is True
