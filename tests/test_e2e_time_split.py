"""A e2e-test test's time is split by agent role, checks and the rest (spec: test-tiers).

The plugin is driven in-process through `pytester` over generated tests, with a ledger
file the generated tests write rows to and a clock the generated tests move.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.e2e import TestTime
from agent_build_kit.pipeline.e2e_times import SPLIT_PREFIX, with_split
from tests import fake_clock, time_split

PRELUDE = """\
import json

import pytest

from tests import time_split


def append(path, *rows):
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + chr(10))


def agent(role, seconds):
    return {
        "kind": "agent", "at": "2030-01-01T09:00:00+00:00", "unit": "feature/1",
        "node": role, "role": role, "duration_ms": seconds * 1000,
    }


def span(seconds, command=""):
    return {
        "kind": "span", "at": "2030-01-01T09:00:00+00:00", "unit": "feature/1",
        "node": "implement", "started": "x", "ended": "y",
        "duration_ms": seconds * 1000, "command": command,
    }


@pytest.fixture
def scratch_ledger(tmp_path):
    return tmp_path / "usage-ledger.jsonl"
"""

MODULE_LEDGER = """\
@pytest.fixture(scope="module")
def scratch_ledger(tmp_path_factory):
    return tmp_path_factory.mktemp("scratch") / "usage-ledger.jsonl"
"""

SPLIT_CALL = """\

@pytest.mark.local_stack
def test_split(scratch_ledger):
    append(scratch_ledger, agent("implement", 120), span(30, "uv run pytest"), span(100))
    time_split.clock.advance(200)
"""


def split_lines(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, body: str
) -> tuple[list[str], list[dict]]:
    """Run generated `local_stack` tests with the plugin; return the output's lines and the
    `ABK-TIME` entries it printed."""
    monkeypatch.setattr(time_split, "clock", fake_clock.FakeClock())
    pytester.makeini("[pytest]\nmarkers =\n    local_stack: an e2e test\n")
    pytester.makepyfile(test_child=PRELUDE + body)
    result = pytester.runpytest_inprocess("-p", "tests.time_split", "-p", "no:cacheprovider")
    assert result.ret == 0, result.outlines
    lines = [line for line in result.outlines if line.startswith(SPLIT_PREFIX)]
    return result.outlines, [json.loads(line[len(SPLIT_PREFIX) :]) for line in lines]


def entry(entries: list[dict], name: str, phase: str) -> dict | None:
    found = [e for e in entries if e["test"].endswith(name) and e["phase"] == phase]
    assert len(found) <= 1, found
    return found[0] if found else None


def test_a_phase_with_an_agent_step_and_a_check_reports_agent_checks_and_the_remainder(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, entries = split_lines(pytester, monkeypatch, SPLIT_CALL)

    call = entry(entries, "::test_split", "call")
    assert call is not None, entries
    assert call["agent"] == {"implement": 120000}
    assert call["calls"] == {"implement": 1}
    assert call["checks_ms"] == 30000
    assert call["other_ms"] == 50000
    assert not call.get("overlap")


def test_two_agent_rows_for_one_role_are_two_calls_and_their_sum(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = """\

@pytest.mark.local_stack
def test_retry(scratch_ledger):
    append(scratch_ledger, agent("implement", 60), agent("implement", 40))
    time_split.clock.advance(300)
"""
    _, entries = split_lines(pytester, monkeypatch, body)

    call = entry(entries, "::test_retry", "call")
    assert call is not None, entries
    assert call["calls"] == {"implement": 2}
    assert call["agent"] == {"implement": 100000}


def test_parts_above_the_wall_time_leave_no_remainder_and_say_they_overlap(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = """\

@pytest.mark.local_stack
def test_parallel(scratch_ledger):
    append(scratch_ledger, agent("implement", 120), span(30, "uv run pytest"))
    time_split.clock.advance(100)
"""
    _, entries = split_lines(pytester, monkeypatch, body)

    call = entry(entries, "::test_parallel", "call")
    assert call is not None, entries
    assert call["other_ms"] == 0
    assert call["overlap"] is True


def test_a_module_fixtures_rows_land_in_the_setup_of_the_first_test_using_it_only(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (
        MODULE_LEDGER
        + """\

@pytest.fixture(scope="module")
def built(scratch_ledger):
    append(scratch_ledger, agent("implement", 90))
    time_split.clock.advance(120)


@pytest.mark.local_stack
def test_first(built):
    pass


@pytest.mark.local_stack
def test_second(built):
    pass
"""
    )
    _, entries = split_lines(pytester, monkeypatch, body)

    with_agent = [(e["test"].rpartition("::")[2], e["phase"]) for e in entries if e.get("agent")]
    assert with_agent == [("test_first", "setup")], entries


def test_a_local_stack_test_without_the_scratch_ledger_gets_no_line(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (
        SPLIT_CALL
        + """\

@pytest.mark.local_stack
def test_plain():
    time_split.clock.advance(5)
"""
    )
    _, entries = split_lines(pytester, monkeypatch, body)

    assert entry(entries, "::test_split", "call") is not None, entries
    assert [e for e in entries if e["test"].endswith("::test_plain")] == []


def test_the_line_round_trips_through_the_framework_reader_and_a_malformed_line_is_ignored(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    outlines, entries = split_lines(pytester, monkeypatch, SPLIT_CALL)
    call = entry(entries, "::test_split", "call")
    assert call is not None, entries
    noisy = "\n".join([SPLIT_PREFIX + "{not json", SPLIT_PREFIX + "[]", *outlines])

    merged = with_split([TestTime(test=call["test"], phase="call", seconds=200.0)], noisy)

    assert merged[0].agent_ms == {"implement": 120000}
    assert merged[0].calls == {"implement": 1}
    assert merged[0].checks_ms == 30000
    assert merged[0].other_ms == 50000


@pytest.mark.parametrize("module", ["test_build_unit.py", "test_graph_unit.py"])
def test_every_test_of_a_live_scratch_module_requests_the_scratch_ledger(
    pytester: pytest.Pytester, module: str
) -> None:
    path = Path(__file__).parent / "integration" / module
    items, _ = pytester.inline_genitems(str(path))

    assert items
    functions = [i for i in items if isinstance(i, pytest.Function)]
    assert len(functions) == len(items)
    assert [f.nodeid for f in functions if time_split.LEDGER_FIXTURE not in f.fixturenames] == []
