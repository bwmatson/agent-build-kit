"""What a tier 2 run exports of each test's time: the histograms `abk.tier2.test.duration`
and `abk.tier2.test.time` with bounded attributes and never a unit id, change name or test
name; an export that raises never fails the run, and with telemetry off nothing is
exported (spec: tier2-time-is-recorded-per-test).

The receiver is an in-process OTLP/HTTP server decoding the bodies the real exporter
posts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.installation import Installation
from tests.otlp import Collector, Point, enabled
from tests.tier2_duration_fakes import (
    E2E,
    durations_output,
    recorded_times,
    run_tier2,
    time_line,
)

TEST = f"{E2E}::test_a"
SPLIT = time_line(
    TEST,
    "call",
    agent={"implement": 120_000},
    calls={"implement": 1},
    checks_ms=30_000,
    other_ms=50_000,
)
OUTPUT = durations_output((842.0, "call", TEST), (3.0, "setup", TEST), lines=(SPLIT,))
BOUNDED = {"marker", "file", "phase", "cause", "role"}


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def _points(collector: Collector) -> list[Point]:
    return [
        *collector.metric("abk.tier2.test.duration"),
        *collector.metric("abk.tier2.test.time"),
    ]


def test_a_phase_adds_its_seconds_with_the_marker_the_file_and_the_phase(
    tmp_path: Path, exported: Collector
) -> None:
    run_tier2(tmp_path, OUTPUT)
    telemetry.shutdown()

    points = {p.attributes["phase"]: p for p in exported.metric("abk.tier2.test.duration")}
    assert {phase: (p.count, p.value) for phase, p in points.items()} == {
        "call": (1, 842.0),
        "setup": (1, 3.0),
    }
    for point in points.values():
        assert point.attributes["marker"] == "local_stack"
        assert point.attributes["file"] == E2E


def test_the_split_adds_a_sample_for_each_cause_and_the_role_only_on_the_agent_one(
    tmp_path: Path, exported: Collector
) -> None:
    run_tier2(tmp_path, OUTPUT)
    telemetry.shutdown()

    by_cause = {p.attributes["cause"]: p for p in exported.metric("abk.tier2.test.time")}
    assert {cause: p.value for cause, p in by_cause.items()} == {
        "agent": 120.0,
        "checks": 30.0,
        "other": 50.0,
    }
    assert by_cause["agent"].attributes["role"] == "implement"
    for cause in ("checks", "other"):
        assert by_cause[cause].attributes.get("role", "") == ""
        assert by_cause[cause].attributes["file"] == E2E


def test_no_attribute_holds_a_unit_id_a_change_name_or_a_test_name(
    tmp_path: Path, exported: Collector
) -> None:
    run_tier2(tmp_path, OUTPUT)
    telemetry.shutdown()

    points = _points(exported)
    assert points
    for point in points:
        assert set(point.attributes) <= BOUNDED, point
        values = [str(value) for value in point.attributes.values()]
        assert not [v for v in values if "add-marker" in v or "test_a" in v], point


def test_a_run_with_no_entries_exports_nothing(tmp_path: Path, exported: Collector) -> None:
    run_tier2(tmp_path, OUTPUT)
    run_tier2(tmp_path, "1 passed in 9.00s", "plain")
    telemetry.shutdown()

    assert {p.attributes["phase"] for p in exported.metric("abk.tier2.test.duration")} == {
        "call",
        "setup",
    }
    assert sum(p.count or 0 for p in exported.metric("abk.tier2.test.duration")) == 2


def test_an_export_that_raises_does_not_fail_the_run(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise RuntimeError("the exporter is down")

    monkeypatch.setattr(telemetry, "meter", refuse)

    result = run_tier2(tmp_path, OUTPUT)

    assert result.ok
    assert [r["phase"] for r in recorded_times(workspace)] == ["call", "setup"]


def test_with_telemetry_off_the_rows_are_written_and_nothing_is_exported(
    tmp_path: Path, workspace: Installation
) -> None:
    with enabled() as collector:
        # enabled() configures the endpoint; nothing has initialised telemetry yet.
        run_tier2(tmp_path, OUTPUT)
        telemetry.shutdown()
        assert collector.posts == []
        assert len(recorded_times(workspace)) == 2

        # The same run with telemetry on is exported, so the silence above is the
        # switch and not an absent feature.
        assert telemetry.init() is True
        run_tier2(tmp_path, OUTPUT, "on")
        telemetry.shutdown()
        assert collector.metric("abk.tier2.test.duration")
