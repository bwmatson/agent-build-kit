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
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_build_kit.usage import Salvaged, Usage

STREAM_FLAGS = ["--output-format", "stream-json", "--verbose"]

# Long enough to say what a message is about, short enough to scan.
WIDTH = 160


class ResultEvent(BaseModel):
    """The `result` event that closes a run: the fields abk reads from it.

    Not `model.Frozen`: the event also carries whatever a later claude adds,
    and a new key there is no reason to lose the one event that says how the run ended.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

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


def stream_run(
    args: list[str],
    *,
    cwd: Path | None,
    on_event: Callable[[dict], None],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `args`, calling `on_event` for each JSON line as it is printed.

    Returns what `subprocess.run` would have: every line of stdout, so the
    refusal check and `final_text` read it exactly as before.
    """
    lines: list[str] = []
    # A file rather than a pipe for stderr: an unread pipe that fills blocks
    # the child, which would then never finish the stdout this loop is reading.
    with tempfile.TemporaryFile("w+") as stderr:
        with subprocess.Popen(
            args, cwd=cwd, stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1, env=env
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)
                event = _parse(line)
                if event is not None:
                    try:
                        on_event(event)
                    except Exception:  # noqa: BLE001, S110
                        pass  # A log line is never worth failing the run over.
        stderr.seek(0)
        return subprocess.CompletedProcess(args, process.returncode, "".join(lines), stderr.read())


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


def describe(event: dict) -> list[str]:
    """One line per thing in `event` worth putting in the log."""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return [f"claude started ({event.get('model', '?')})"]
    if kind == "assistant":
        return [line for block in _content(event) if (line := _block(block))]
    if kind == "result":
        seconds = round((event.get("duration_ms") or 0) / 1000)
        turns = event.get("num_turns", "?")
        outcome = "error" if event.get("is_error") else "done"
        return [f"claude {outcome} — {turns} turns, {seconds // 60}m{seconds % 60:02d}s"]
    return []


def _block(block: dict) -> str:
    if block.get("type") == "text":
        return f"says: {_short(block.get('text', ''))}" if block.get("text", "").strip() else ""
    if block.get("type") == "tool_use":
        return f"{block.get('name', '?')} {_short(_tool_target(block.get('input') or {}))}".rstrip()
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
