"""The `result` event that closes a Claude run is read for what the run spent:
tokens by kind, cost, turns, duration and the session. Every one is optional
and an unknown field is no reason to lose the rest (spec: agent-usage-capture).

The events are what `claude -p --output-format stream-json` prints
(`tests/runtimes/claude_cli.py`), with the fields the reader does not use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.claude_stream import result_event
from agent_build_kit.usage import Usage
from tests.runtimes.claude_cli import SESSION, finished_build, record


def closing(stdout: str) -> dict:
    return json.loads(stdout.strip().splitlines()[-1])


def test_a_recorded_result_event_gives_its_tokens_cost_turns_duration_and_session(
    tmp_path: Path,
) -> None:
    event = result_event(finished_build(tmp_path, "done"))

    assert event is not None
    usage = cast(Usage, event.usage)
    assert usage.input_tokens == 4
    assert usage.output_tokens == 212
    assert usage.cache_read_input_tokens == 14671
    assert usage.cache_creation_input_tokens == 1822
    assert event.total_cost_usd == 0.4127
    assert event.num_turns == 3
    assert event.duration_ms == 81234
    assert event.session_id == SESSION


FIGURES = {
    "usage": lambda e: e.usage,
    "total_cost_usd": lambda e: e.total_cost_usd,
    "duration_ms": lambda e: e.duration_ms,
    "num_turns": lambda e: e.num_turns,
    "session_id": lambda e: e.session_id,
}


@pytest.mark.parametrize("missing", FIGURES)
def test_an_event_missing_a_figure_still_parses_and_the_figure_is_absent_not_zero(
    missing: str,
) -> None:
    payload = closing(record("done"))
    del payload[missing]

    event = result_event(json.dumps(payload) + "\n")

    assert event is not None
    assert event.result == "done"
    assert FIGURES[missing](event) is None
    for name, read in FIGURES.items():
        if name != missing:
            assert read(event) is not None, f"{name} is still there to be read"


def test_a_usage_that_omits_a_kind_leaves_that_kind_absent() -> None:
    payload = closing(record("done"))
    payload["usage"] = {"output_tokens": 90}

    event = result_event(json.dumps(payload) + "\n")

    assert event is not None
    usage = cast(Usage, event.usage)
    assert usage.output_tokens == 90
    assert usage.input_tokens is None
    assert usage.cache_read_input_tokens is None
    assert usage.cache_creation_input_tokens is None


def test_a_field_the_reader_does_not_know_changes_nothing_it_does() -> None:
    payload = closing(record("done"))
    payload["usage"]["server_tool_use"] = {"web_search_requests": 2}
    payload["usage"]["iterations"] = [{"input_tokens": 4}]
    payload["a_field_a_later_claude_adds"] = {"nested": [1, 2, 3]}

    event = result_event(json.dumps(payload) + "\n")

    assert event is not None
    usage = cast(Usage, event.usage)
    assert (usage.input_tokens, usage.output_tokens) == (4, 212)
    assert event.total_cost_usd == 0.4127
    assert event.session_id == SESSION
