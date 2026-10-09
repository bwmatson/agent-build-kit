"""The recorded history of a unit's agent runs and chat turns (docs/architecture.md).

One file per agent call, one JSON event per line, appended as the agent streams. The
same shape for every runtime; tool results are cut at a configured size.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from agent_build_kit.model import Frozen

if TYPE_CHECKING:
    # units imports config, which imports the runtimes, which carry a TranscriptEvent.
    from agent_build_kit.pipeline.units import Unit

EventKind = Literal[
    "text", "reasoning", "tool_call", "tool_result", "plan", "usage", "permission", "stop", "user"
]
Source = Literal["build", "chat"]


class TranscriptEvent(Frozen):
    """One line of a transcript. A runtime sets the kind, the session and what the
    event says; the `Transcript` it is handed to adds the time, unit, node, round and source."""

    kind: EventKind
    at: str = ""
    unit: str = ""
    node: str = ""
    round: int = 0
    session: str = ""
    source: Source = "build"
    text: str = ""  # what was said, a tool result, a plan, or the stop reason
    tool: str = ""  # a tool call's tool
    call: str = ""  # a tool call's id, which its result repeats
    input: dict[str, Any] = {}  # a tool call's input
    usage: dict[str, int] = {}  # a usage event's counts
    truncated: int | None = None  # a cut tool result's original length


class SessionHistory(Frozen):
    """What a runtime keeps of a session it was not recorded in."""

    events: tuple[TranscriptEvent, ...] = ()
    tool_calls: bool = False  # whether the runtime's own record has the tool calls


class Replay(Frozen):
    """The history the agent tab shows."""

    events: tuple[TranscriptEvent, ...] = ()
    recorded: bool = True  # False: read from the runtime's own record
    tool_calls_available: bool = True


def transcript_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory."""
    return state_dir / "transcripts"


def _prefix(unit: Unit) -> str:
    number = int(unit.id.rsplit("/", 1)[1])
    return f"{unit.change}-{number:02d}-"


def _unit_files(directory: Path, prefix: str) -> list[Path]:
    """The files of the unit whose prefix this is: a stamp follows it directly,
    so a unit whose number merely begins with another's is not matched."""
    pattern = re.compile(re.escape(prefix) + r"\d{8}-\d{6}-")
    try:
        return sorted(path for path in directory.iterdir() if pattern.match(path.name))
    except OSError:
        return []


class Transcript:
    """One agent call's file. Every call of a run (a unit thread's pass, or one chat
    turn) is opened with that run's `started` stamp, and retention counts runs by
    it, as the run log does: the runs beyond `runs_kept` go whole, oldest first. A
    diagnostic copy, so a write that fails is dropped: it never affects the run it
    records."""

    def __init__(
        self,
        directory: Path,
        unit: Unit,
        *,
        node: str,
        round: int,
        source: Source = "build",
        started: datetime,
        result_limit: int,
        runs_kept: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit = unit.id
        self._node = node
        self._round = round
        self._source: Source = source
        self._limit = result_limit
        self._clock = clock
        name = f"{_prefix(unit)}{started:%Y%m%d-%H%M%S}-{node}-{round}.jsonl"
        self._path = directory / name
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._path.touch()
            files = _unit_files(directory, _prefix(unit))
            skip = len(_prefix(unit))
            older = set(sorted({path.name[skip : skip + 15] for path in files})[:-runs_kept])
            for old in files:
                if old.name[skip : skip + 15] in older:
                    old.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def path(self) -> Path:
        return self._path

    def record(self, event: TranscriptEvent) -> None:
        """Append `event`, stamped, as one line the moment it arrives."""
        fields: dict[str, Any] = {
            "at": self._clock().isoformat(),
            "unit": self._unit,
            "node": self._node,
            "round": self._round,
            "source": self._source,
        }
        if event.kind == "tool_result" and len(event.text) > self._limit:
            length = len(event.text)
            fields["text"] = (
                f"{event.text[: self._limit]}\n… [cut: the result was {length} characters long]"
            )
            fields["truncated"] = length
        line = event.model_copy(update=fields).model_dump_json()
        try:
            with self._path.open("a") as file:
                file.write(line + "\n")
        except (OSError, ValueError):
            pass


def unit_transcript_files(directory: Path, unit_id: str) -> list[Path]:
    """The unit's transcript files, oldest run first."""
    change, number = unit_id.rsplit("/", 1)
    return _unit_files(directory, f"{change}-{int(number):02d}-")


def read_file_events(path: Path, skip: int = 0) -> tuple[list[TranscriptEvent], int]:
    """The events of one transcript file after its first `skip` lines, and how many lines
    have now been read. A last line not yet ended is left for the next read, so a reader
    that keeps the count never skips an event, whatever happens to other files."""
    try:
        text = path.read_text()
    except OSError:
        return [], skip
    lines = text.split("\n")[:-1]
    events: list[TranscriptEvent] = []
    for line in lines[skip:]:
        try:
            events.append(TranscriptEvent.model_validate_json(line))
        except ValueError:
            continue
    return events, max(skip, len(lines))


def read_transcripts(directory: Path, unit_id: str) -> list[TranscriptEvent]:
    """Every recorded event of the unit, across runs and chat turns, in time order."""
    change, number = unit_id.rsplit("/", 1)
    events: list[TranscriptEvent] = []
    for path in _unit_files(directory, f"{change}-{int(number):02d}-"):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                events.append(TranscriptEvent.model_validate_json(line))
            except ValueError:
                continue  # a line half written when the run was killed
    return events


def remove_change_transcripts(directory: Path, change: str) -> None:
    """Drop every transcript of a change. A directory that cannot be read leaves
    the archive it follows standing."""
    pattern = re.compile(re.escape(change) + r"-\d{2,}-\d{8}-\d{6}-")
    try:
        for path in directory.iterdir():
            if pattern.match(path.name):
                path.unlink(missing_ok=True)
    except OSError:
        return


def replay(
    directory: Path,
    unit_id: str,
    session: str,
    *,
    runtime_history: Callable[[str], SessionHistory],
) -> Replay:
    """The unit's recorded history; a `session` it never recorded is read from the runtime."""
    events = read_transcripts(directory, unit_id)
    if any(event.session == session for event in events):
        return Replay(events=tuple(events))
    history = runtime_history(session)
    return Replay(events=history.events, recorded=False, tool_calls_available=history.tool_calls)
