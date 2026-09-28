"""Showing a Claude run's progress while it happens.

The events here are the shapes `claude -p --output-format stream-json`
prints; the tests pin the few fields the log reads from them.
"""

import json
import sys
from pathlib import Path

from agent_build_kit.pipeline.claude_stream import describe, final_text, stream_run

RESULT = {"type": "result", "result": "the answer", "num_turns": 12, "duration_ms": 754_000}


def assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def test_a_tool_call_is_logged_as_the_tool_and_what_it_acts_on() -> None:
    event = assistant({"type": "tool_use", "name": "Edit", "input": {"file_path": "src/x.py"}})

    assert describe(event) == ["Edit src/x.py"]


def test_what_the_model_says_is_logged_on_one_short_line() -> None:
    event = assistant({"type": "text", "text": "First I will\nread the spec. " + "x" * 400})

    (line,) = describe(event)
    assert line.startswith("says: First I will read the spec.")
    assert len(line) < 200


def test_the_end_of_a_run_says_how_long_it_took() -> None:
    assert describe(RESULT) == ["claude done — 12 turns, 12m34s"]


def test_tool_results_are_not_logged() -> None:
    """They are file contents and command output — the log would be the
    transcript."""
    assert describe({"type": "user", "message": {"content": [{"type": "tool_result"}]}}) == []


def test_the_answer_is_the_result_event_s_text() -> None:
    stream = "\n".join(json.dumps(e) for e in [assistant(), RESULT])

    assert final_text(stream) == "the answer"


def test_output_that_is_not_a_stream_is_the_answer_as_it_stands() -> None:
    assert final_text("did the thing") == "did the thing"


def test_events_reach_the_callback_while_the_run_is_going(tmp_path: Path) -> None:
    script = "import json; [print(json.dumps({'type': 'n', 'n': n}), flush=True) for n in range(3)]"
    seen: list[dict] = []

    result = stream_run([sys.executable, "-c", script], cwd=tmp_path, on_event=seen.append)

    assert [event["n"] for event in seen] == [0, 1, 2]
    assert result.returncode == 0
    assert result.stdout.count("\n") == 3, "stdout is kept whole for the refusal check"


def test_a_broken_callback_does_not_break_the_run(tmp_path: Path) -> None:
    def explode(event: dict) -> None:
        raise ValueError("bad log line")

    result = stream_run([sys.executable, "-c", "print('{}')"], cwd=tmp_path, on_event=explode)

    assert result.returncode == 0
