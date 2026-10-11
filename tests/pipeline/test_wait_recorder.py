"""The decision log records a change of wait reason once, and a wait that ends is one span
(spec: unit-timeline-is-recorded).

The recorder is told, each pass, what every waiting unit waits for; the log is a file in
the state directory, so a restart is a second recorder on the same path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import Wait, WaitRecorder
from tests.fake_clock import START, FakeClock, install, span_lines
from tests.otlp import Collector, enabled

UNIT = "add-marker/2"
PREREQUISITE = "add-marker/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def log_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def blocked(on: str = PREREQUISITE) -> dict[str, Wait]:
    return {UNIT: Wait(reason=WaitReason.BLOCKED, waits_on=(on,))}


def waiting(reason: WaitReason) -> dict[str, Wait]:
    return {UNIT: Wait(reason=reason)}


def test_a_new_reason_is_one_record_with_what_it_waits_on(tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "decisions.jsonl"

    WaitRecorder(path, print).record(blocked(), tick="t1")

    assert log_of(path) == [
        {
            "at": START.isoformat(),
            "unit": UNIT,
            "reason": "blocked",
            "waits_on": [PREREQUISITE],
            "tick": "t1",
        }
    ]


def test_ten_thousand_ticks_of_the_same_wait_write_one_record(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    recorder = WaitRecorder(path, print)

    for tick in range(10_000):
        clock.advance(1)
        recorder.record(blocked(), tick=f"t{tick}")

    assert len(log_of(path)) == 1


def test_a_change_of_what_it_waits_on_is_a_new_record(tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "decisions.jsonl"
    recorder = WaitRecorder(path, print)

    recorder.record(blocked(PREREQUISITE), tick="t1")
    recorder.record(blocked("add-marker/0"), tick="t2")

    assert [line["waits_on"] for line in log_of(path)] == [[PREREQUISITE], ["add-marker/0"]]


def test_a_prerequisite_that_merges_into_a_wait_for_a_slot_appends_the_new_reason(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    recorder = WaitRecorder(path, print)
    recorder.record(blocked(), tick="t1")

    recorder.record(waiting(WaitReason.SLOT), tick="t2")

    assert [(line["reason"], line["tick"]) for line in log_of(path)] == [
        ("blocked", "t1"),
        ("slot", "t2"),
    ]


def test_a_unit_that_stops_waiting_gets_one_closing_record(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    recorder = WaitRecorder(path, print)
    recorder.record(blocked(), tick="t1")

    clock.advance(60)
    recorder.record({}, tick="t2")
    recorder.record({}, tick="t3")

    closing = log_of(path)[1:]
    assert [(line["unit"], line["reason"], line["tick"]) for line in closing] == [
        (UNIT, "none", "t2")
    ]
    assert closing[0]["at"] == (START + timedelta(seconds=60)).isoformat()


def test_a_restarted_recorder_resumes_from_the_tail_without_repeating_the_last_reason(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    WaitRecorder(path, print).record(blocked(), tick="t1")

    restarted = WaitRecorder(path, print)
    restarted.record(blocked(), tick="t2")
    assert len(log_of(path)) == 1

    restarted.record(waiting(WaitReason.SLOT), tick="t3")
    assert [line["reason"] for line in log_of(path)] == ["blocked", "slot"]


def test_a_restarted_recorder_knows_a_wait_that_had_already_closed(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    first = WaitRecorder(path, print)
    first.record(blocked(), tick="t1")
    first.record({}, tick="t2")

    WaitRecorder(path, print).record({}, tick="t3")

    assert len(log_of(path)) == 2


def test_a_failing_write_is_told_once_and_does_not_fail_the_pass(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "decisions.jsonl"
    path.mkdir()  # a directory cannot be appended to
    said: list[str] = []
    recorder = WaitRecorder(path, said.append)

    recorder.record(blocked(), tick="t1")
    recorder.record(waiting(WaitReason.SLOT), tick="t2")

    assert len(said) == 1


# --- a wait is one span -------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [WaitReason.QUEUE_FULL, WaitReason.LEASE, WaitReason.BACKOFF, WaitReason.NEEDS_PERSON],
)
def test_a_wait_that_ends_is_one_span_carrying_its_reason_and_no_node(
    workspace: Installation, tmp_path: Path, clock: FakeClock, reason: WaitReason
) -> None:
    recorder = WaitRecorder(tmp_path / "decisions.jsonl", print)
    recorder.record(waiting(reason), tick="t1")
    clock.advance(90)
    recorder.record(waiting(reason), tick="t2")
    assert span_lines(workspace) == [], "a wait that is still going has not ended"

    clock.advance(30)
    recorder.record({}, tick="t3")

    (span,) = span_lines(workspace)
    assert span["unit"] == UNIT
    assert span["waited"] == reason
    assert span["node"] == ""
    assert span["duration_ms"] == 120_000
    assert span["started"] == START.isoformat()


def test_a_change_of_reason_closes_the_span_of_the_one_before(
    workspace: Installation, tmp_path: Path, clock: FakeClock
) -> None:
    recorder = WaitRecorder(tmp_path / "decisions.jsonl", print)
    recorder.record(waiting(WaitReason.QUEUE_FULL), tick="t1")
    clock.advance(45)

    recorder.record(waiting(WaitReason.LEASE), tick="t2")

    (span,) = span_lines(workspace)
    assert (span["waited"], span["duration_ms"]) == ("queue_full", 45_000)


@pytest.mark.parametrize("reason", [WaitReason.SLOT, WaitReason.USAGE_PAUSE])
def test_a_wait_the_build_path_already_records_is_not_recorded_twice(
    workspace: Installation, tmp_path: Path, clock: FakeClock, reason: WaitReason
) -> None:
    recorder = WaitRecorder(tmp_path / "decisions.jsonl", print)
    recorder.record(waiting(reason), tick="t1")
    clock.advance(30)

    recorder.record({}, tick="t2")

    assert span_lines(workspace) == []


def test_a_wait_adds_its_time_to_the_wait_metric_once(
    workspace: Installation, tmp_path: Path, clock: FakeClock, exported: Collector
) -> None:
    recorder = WaitRecorder(tmp_path / "decisions.jsonl", print)
    recorder.record(waiting(WaitReason.LEASE), tick="t1")
    clock.advance(120)
    recorder.record({}, tick="t2")
    telemetry.shutdown()

    (point,) = exported.metric("abk.wait.duration")
    assert point.attributes == {"bucket": "lease"}
    assert (point.count, point.value) == (1, 120)
