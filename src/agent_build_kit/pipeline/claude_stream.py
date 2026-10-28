"""Running `claude -p` with its progress visible in the tick log.

A unit's build is four or more Claude runs of twenty-odd minutes each, and the
tick log used to say "ready: <unit>" and then nothing until the end — the only
way to see what was happening was to find the worktree and read its diff.

`--output-format stream-json` makes claude emit one JSON event per line as it
works. `stream_run` reads them as they arrive and hands each to a callback, and
`describe` turns the ones worth reading — what the model says, which tool it
calls on what — into a single log line. The final `result` event carries the
same text plain `-p` would have printed, which `final_text` extracts so callers
see no difference.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_build_kit.pipeline.install_record import logged_lines
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.usage import Salvaged, Usage

STREAM_FLAGS = ["--output-format", "stream-json", "--verbose"]

# Long enough to say what a message is about, short enough to scan.
WIDTH = 160


class ResultEvent(BaseModel):
    """The `result` event that closes a run: the fields abk reads from it.

    Not `model.Frozen`: the event also carries whatever a later claude adds,
    and a new key there is no reason to lose the one event that says how the run ended.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    type: Literal["result"]
    # `success`, or an error subtype: `error_during_execution`, `error_max_turns`.
    subtype: str = ""
    # The run ended in an error, whatever the subtype says.
    is_error: bool = False
    # A `success` result's answer; an error subtype has none.
    result: str | None = None
    # What went wrong, on an error subtype.
    errors: list[str] = []
    # The HTTP status of the API error that ended the run: `null` on a clean one.
    api_error_status: Annotated[int | None, Salvaged] = None
    # How many turns the run took, and the tokens it spent, when it says.
    num_turns: int | None = None
    # Absent when the event carries none: a count it omits is None, never zero.
    # A figure of the wrong type is None: it must not lose the event.
    usage: Annotated[Usage | None, Salvaged] = None
    total_cost_usd: Annotated[float | None, Salvaged] = None
    duration_ms: Annotated[int | None, Salvaged] = None
    session_id: Annotated[str | None, Salvaged] = None
    # Per model, what the run spent; a newer claude adds each model's `contextWindow`.
    model_usage: Annotated[dict[str, dict] | None, Salvaged] = Field(
        default=None, alias="modelUsage"
    )

    def context_window(self, *models: str | None) -> int | None:
        """The window the first of `models` that the event lists ran in; the only model's
        when none is listed. The event keys its entries by the model's full id, which is
        neither a configured alias nor always the one model: background requests add others.
        A figure that is not a positive whole number is absent."""
        entries = self.model_usage or {}
        entry = next((entries[m] for m in models if m and m in entries), None)
        if entry is None and len(entries) == 1:
            entry = next(iter(entries.values()))
        window = entry.get("contextWindow") if isinstance(entry, dict) else None
        if isinstance(window, int) and not isinstance(window, bool) and window > 0:
            return window
        return None


def started_model(stdout: str) -> str | None:
    """The model the run's init event names: what `describe` prints as `claude started
    (<model>)`. It is there before the first answer, so a run cut off early still has it."""
    for line in stdout.splitlines():
        event = _parse(line)
        if event is not None and event.get("type") == "system" and event.get("subtype") == "init":
            model = event.get("model")
            return model if isinstance(model, str) and model else None
    return None


def request_fills(stdout: str) -> tuple[list[int], int, str | None]:
    """The main conversation's context fill at each model request of a streamed run, in
    order, how many times the run said it compacted, and the model id it ran on. An assistant
    event repeats its request's message once per content block, which counts once; a
    sub-agent's requests (those naming the tool call that started them) are not the main
    context."""
    fills: list[int] = []
    markers = 0
    model: str | None = None
    seen: str | None = None
    for line in stdout.splitlines():
        event = _parse(line)
        if event is None:
            continue
        if event.get("type") == "system" and event.get("subtype") == "compact_boundary":
            markers += 1
        elif event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            counts = [
                usage.get(key)
                for key in (
                    "input_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            ]
            whole = [n for n in counts if isinstance(n, int) and not isinstance(n, bool)]
            if message.get("id") == seen or len(whole) != len(counts):
                continue
            seen = message.get("id")
            model = model or message.get("model")
            fills.append(sum(whole))
    return fills, markers, model


def stream_run(
    args: list[str],
    *,
    cwd: Path | None,
    on_event: Callable[[dict], None],
    env: dict[str, str] | None = None,
    input: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run `args` with `input` on its standard input, calling `on_event` for each JSON line
    as it is printed.

    Returns what `subprocess.run` would have: every line of stdout, so the
    refusal check and `final_text` read it exactly as before.
    """
    lines: list[str] = []
    # A file rather than a pipe for stderr: an unread pipe that fills blocks
    # the child, which would then never finish the stdout this loop is reading.
    with tempfile.TemporaryFile("w+") as stderr:
        with subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            encoding="utf-8",
            bufsize=1,
            env=env,
        ) as process:
            assert process.stdout is not None and process.stdin is not None
            # From a thread, so a prompt larger than the pipe cannot block before the output
            # is read; closed when written, so the process sees the end of its input.
            feeder = threading.Thread(target=_feed, args=(process.stdin, input))
            feeder.start()
            for line in process.stdout:
                lines.append(line)
                event = _parse(line)
                if event is not None:
                    try:
                        on_event(event)
                    except Exception:  # noqa: BLE001, S110
                        pass  # A log line is never worth failing the run over.
            # Joined before the `with` closes the pipe, so only the feeder closes stdin.
            feeder.join()
        stderr.seek(0)
        return subprocess.CompletedProcess(args, process.returncode, "".join(lines), stderr.read())


def _feed(pipe: IO[str], text: str) -> None:
    """Write `text` to a child's standard input and close it; a child that exits early is fine."""
    try:
        with pipe:
            pipe.write(text)
    except OSError:
        pass


def final_text(stdout: str) -> str:
    """The run's answer: the `result` event's text, or stdout as it stands
    when it is not a stream (an injected runner in a test, or an old claude)."""
    event = result_event(stdout)
    return event.result if event is not None and event.result is not None else stdout


def result_event(stdout: str) -> ResultEvent | None:
    """The run's closing `result` event, or None when there is none or it is
    not the shape a result event has."""
    for line in reversed(stdout.splitlines()):
        event = _parse(line)
        if event and event.get("type") == "result":
            try:
                return ResultEvent.model_validate(event)
            except ValidationError:
                return None
    return None


def own_words(stdout: str) -> str:
    """What the CLI itself said about how the run ended, and nothing the run
    did on the way: the `result` event's text and its `errors`, or, with no
    such event, the lines that are not events.

    Which of the two the event carries depends on its subtype: a `success`
    result (a usage-limit refusal among them, flagged `is_error`) says it in
    `result`; an error subtype (`error_during_execution`, `error_max_turns`)
    has no `result` and lists what went wrong in `errors`.

    A failed run is classified on this, never on the whole transcript. A
    stream carries every event's uuid, token counts, the files the agent read
    and its own prose, any of which can contain "429" or "rate limit" — so
    reading all of it turns an ordinary failure into a pause.
    """
    event = result_event(stdout)
    if event is not None:
        return "\n".join(part for part in [event.result, *event.errors] if part)
    return "\n".join(line for line in stdout.splitlines() if _parse(line) is None)


def describe(event: dict, *, whole: bool = False) -> list[str]:
    """One line per thing in `event` worth putting in the log. `whole` keeps a
    reply or a command as written, line breaks and all, instead of clipping it."""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return [f"claude started ({event.get('model', '?')})"]
    if kind == "assistant":
        return [line for block in _content(event) if (line := _block(block, whole))]
    if kind == "user":
        return [
            line
            for block in _content(event)
            if block.get("type") == "tool_result"
            for line in logged_lines(_result_text(block.get("content")))
        ]
    if kind == "result":
        seconds = round((event.get("duration_ms") or 0) / 1000)
        turns = event.get("num_turns", "?")
        outcome = "error" if event.get("is_error") else "done"
        return [f"claude {outcome} — {turns} turns, {seconds // 60}m{seconds % 60:02d}s"]
    return []


def records(event: dict) -> list[TranscriptEvent]:
    """The transcript events in one stream event, in the shape every runtime shares."""
    kind = event.get("type")
    session = str(event.get("session_id") or "")
    found: list[TranscriptEvent] = []
    if kind in ("assistant", "user"):
        for block in _content(event):
            # A `user` event is the harness speaking: a skill's expanded body or an
            # interruption notice is text there that the agent did not write.
            if kind == "user" and block.get("type") != "tool_result":
                continue
            if (made := _record_of(block)) is not None:
                found.append(made.model_copy(update={"session": session}))
    elif kind == "result":
        counts = {
            key: value
            for key, value in (event.get("usage") or {}).items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if counts:
            found.append(TranscriptEvent(kind="usage", session=session, usage=counts))
        found.append(
            TranscriptEvent(kind="stop", session=session, text=str(event.get("subtype") or ""))
        )
    return found


def _record_of(block: dict) -> TranscriptEvent | None:
    match block.get("type"):
        case "text" if block.get("text", "").strip():
            return TranscriptEvent(kind="text", text=block["text"])
        case "thinking" if block.get("thinking", "").strip():
            return TranscriptEvent(kind="reasoning", text=block["thinking"])
        case "tool_use":
            return TranscriptEvent(
                kind="tool_call",
                tool=str(block.get("name") or ""),
                call=str(block.get("id") or ""),
                input=block.get("input") or {},
            )
        case "tool_result":
            return TranscriptEvent(
                kind="tool_result",
                call=str(block.get("tool_use_id") or ""),
                text=_result_text(block.get("content")),
            )
    return None


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def _block(block: dict, whole: bool = False) -> str:
    keep = (lambda text: text.strip()) if whole else _short
    if block.get("type") == "text":
        return f"says: {keep(block.get('text', ''))}" if block.get("text", "").strip() else ""
    if block.get("type") == "tool_use":
        return f"{block.get('name', '?')} {keep(_tool_target(block.get('input') or {}))}".rstrip()
    return ""


def _tool_target(tool_input: dict) -> str:
    """What a tool call acts on — the part that says what the model is doing."""
    for key in ("file_path", "path", "command", "pattern", "url", "description"):
        if value := tool_input.get(key):
            return str(value)
    return ""


def _content(event: dict) -> list[dict]:
    content = (event.get("message") or {}).get("content") or []
    return [block for block in content if isinstance(block, dict)]


def _short(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= WIDTH else flat[: WIDTH - 1] + "…"


def _parse(line: str) -> dict | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
