"""What a tick leaves in the local metric records, with telemetry off, and how
those records agree with what telemetry exports when it is on (spec: telemetry).

The tick runs through `cmd_tick` over the same fakes as the telemetry tests; the
records are read back from the usage ledger by the module's own reader.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.metric_records import MetricRecord, read_metrics
from agent_build_kit.pipeline.usage_guard import Decision, RateLimited
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.cli.test_tick_telemetry import (  # noqa: F401 — fixtures
    FAILING,
    UNIT,
    Ticks,
    ticks,
)
from tests.otlp import Collector, enabled
from tests.runner_fakes import rejecting


@pytest.fixture
def exported() -> Iterator[None]:
    """The `ticks` fixture asks for this one; here telemetry stays off."""
    yield None


@pytest.fixture
def collector() -> Iterator[Collector]:
    with enabled() as received:
        yield received


def records(ticks: Ticks, metric: str) -> list[MetricRecord]:  # noqa: F811 — fixture
    found = read_metrics(ticks.inst.state_dir / LEDGER_NAME)
    return [record for record in found if record.metric == metric]


def pause_for_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    resume = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(may_start=False, reason="session usage at 90%", resume_at=resume),
    )


# --- with telemetry off -------------------------------------------------------------


def test_a_tick_appends_its_duration_and_how_it_ended(ticks: Ticks) -> None:  # noqa: F811
    ticks.agents()

    assert ticks.tick() == 0

    (tick,) = records(ticks, "abk.tick.duration")
    assert tick.attributes == {"outcome": "built"}
    assert tick.value >= 0
    assert tick.kind == "metric"


def test_a_pause_for_the_usage_window_appends_a_record_with_its_kind(
    ticks: Ticks,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pause_for_usage(monkeypatch)

    ticks.tick()

    (pause,) = records(ticks, "abk.usage.pauses")
    assert pause.attributes == {"kind": "usage"}
    assert pause.value == 1


def test_a_rate_limit_pause_appends_a_record_with_its_kind(ticks: Ticks) -> None:  # noqa: F811
    def refused(*args: Any, **kwargs: Any) -> str:
        raise RateLimited("usage limit reached", resets_at=datetime.now(UTC) + timedelta(hours=2))

    ticks.options["run_claude"] = refused

    ticks.tick()

    assert [p.attributes for p in records(ticks, "abk.usage.pauses")] == [{"kind": "rate_limit"}]


def test_a_unit_reviewed_twice_appends_its_rounds_and_a_check_failure(
    ticks: Ticks,  # noqa: F811
) -> None:
    ticks.recorder.verdicts = [rejecting("rename the lock")]
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.agents()

    ticks.tick()

    (rounds,) = records(ticks, "abk.review.rounds")
    assert rounds.value == 2
    assert rounds.attributes == {"repo": "app", "outcome": "open"}
    assert (rounds.unit, rounds.change) == (UNIT, "add-marker")
    failures = records(ticks, "abk.checks.failures")
    assert [(f.attributes["check"], f.value) for f in failures] == [("types", 1)]
    assert all(set(f.attributes) == {"check", "round"} for f in failures)
    assert all(f.unit == UNIT for f in failures)


def test_a_units_outcome_appends_a_record_with_its_repo_tier_and_outcome(
    ticks: Ticks,  # noqa: F811
) -> None:
    ticks.agents()

    ticks.tick()

    (outcome,) = records(ticks, "abk.unit.duration")
    assert outcome.attributes == {"repo": "app", "tier": "tier1", "outcome": "open"}
    assert (outcome.unit, outcome.change) == (UNIT, "add-marker")
    assert outcome.value >= 0


def test_a_failed_unit_appends_the_failed_outcome(ticks: Ticks) -> None:  # noqa: F811
    ticks.recorder.tier1_ok = False
    ticks.recorder.tier1_output = "E   ImportError: cannot import 'geo'"
    ticks.agents()

    ticks.tick()

    (outcome,) = records(ticks, "abk.unit.duration")
    assert outcome.attributes["outcome"] == "failed"


# --- against what telemetry exports ---------------------------------------------------


def test_durations_and_counts_in_the_records_equal_the_exported_figures(
    ticks: Ticks,  # noqa: F811
    collector: Collector,
) -> None:
    ticks.recorder.verdicts = [rejecting("rename the lock")]
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.agents()

    assert ticks.tick() == 0

    for name in ("abk.tick.duration", "abk.unit.duration", "abk.review.rounds"):
        (point,) = collector.metric(name)
        (record,) = records(ticks, name)
        assert record.attributes == point.attributes, name
        assert record.value == pytest.approx(point.value, rel=1e-9), name
    exported = {
        (p.attributes["check"], p.attributes["round"]): p.value
        for p in collector.metric("abk.checks.failures")
    }
    local: dict[tuple[Any, Any], float] = {}
    for record in records(ticks, "abk.checks.failures"):
        key = (record.attributes["check"], record.attributes["round"])
        local[key] = local.get(key, 0) + record.value
    assert exported and local == exported


def test_pauses_in_the_records_equal_the_exported_count(
    ticks: Ticks,  # noqa: F811
    collector: Collector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pause_for_usage(monkeypatch)

    ticks.tick()

    (point,) = collector.metric("abk.usage.pauses")
    assert sum(r.value for r in records(ticks, "abk.usage.pauses")) == point.value
    assert [r.attributes for r in records(ticks, "abk.usage.pauses")] == [point.attributes]
