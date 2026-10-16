"""The six places a tick emits a metric that also has a local record reach the one
function that does both (spec: dry-cleanup, a metric with a local record is emitted
through one function).

A tick runs through `cmd_tick` over the same fakes as the telemetry tests, with
telemetry off; what each site passes to the helper is read from a spy that still
calls the real one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph import unit as unit_graph
from agent_build_kit.pipeline.metric_records import InstrumentKind, emit_metric
from agent_build_kit.pipeline.usage_guard import Decision, RateLimited
from tests.cli.test_tick_telemetry import (  # noqa: F401 — fixtures
    FAILING,
    UNIT,
    Ticks,
    allow_once_then_refuse,
    ticks,
)
from tests.runner_fakes import rejecting

Emitted = tuple[str, str, float, str, str, dict[str, Any]]


@pytest.fixture
def exported() -> Iterator[None]:
    """The `ticks` fixture asks for this one; here telemetry stays off."""
    yield None


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[Emitted]:
    """Every call a site makes to the helper: instrument, name, value, unit, change, attributes."""
    calls: list[Emitted] = []

    def spy(
        instrument: InstrumentKind,
        name: str,
        value: float,
        say: Callable[[str], None],
        /,
        *,
        unit: str = "",
        change: str = "",
        **attributes: Any,
    ) -> None:
        calls.append((instrument, name, value, unit, change, attributes))
        emit_metric(instrument, name, value, say, unit=unit, change=change, **attributes)

    monkeypatch.setattr(cli, "emit_metric", spy)
    monkeypatch.setattr(unit_graph, "emit_metric", spy)
    return calls


def named(emitted: list[Emitted], name: str) -> list[Emitted]:
    return [call for call in emitted if call[1] == name]


def test_the_tick_duration_goes_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
) -> None:
    ticks.agents()

    ticks.tick()

    ((instrument, _, value, unit, change, attributes),) = named(emitted, "abk.tick.duration")
    assert (instrument, unit, change) == ("duration", "", "")
    assert attributes == {"outcome": "built"}
    assert value >= 0


def test_a_usage_pause_of_the_tick_goes_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(may_start=False, reason="session usage at 90%", resume_at=resume),
    )

    ticks.tick()

    assert named(emitted, "abk.usage.pauses") == [
        ("count", "abk.usage.pauses", 1, "", "", {"kind": "usage"})
    ]


def test_a_rate_limit_pause_goes_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
) -> None:
    def refused(*args: Any, **kwargs: Any) -> str:
        raise RateLimited("usage limit reached", resets_at=datetime.now(UTC) + timedelta(hours=2))

    ticks.options["run"] = refused

    ticks.tick()

    assert named(emitted, "abk.usage.pauses") == [
        ("count", "abk.usage.pauses", 1, UNIT, "add-marker", {"kind": "rate_limit"})
    ]


def test_a_usage_pause_met_by_a_unit_goes_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks.agents()
    ticks.options["may_start"] = lambda: (False, "session usage at 88%")
    ticks.options["resume_at"] = lambda: datetime.now(UTC) + timedelta(hours=1)
    allow_once_then_refuse(monkeypatch)

    ticks.tick()

    assert ("count", "abk.usage.pauses", 1, UNIT, "add-marker", {"kind": "usage"}) in named(
        emitted, "abk.usage.pauses"
    )


def test_a_units_duration_goes_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
) -> None:
    ticks.agents()

    ticks.tick()

    ((instrument, _, value, unit, change, attributes),) = named(emitted, "abk.unit.duration")
    assert (instrument, unit, change) == ("duration", UNIT, "add-marker")
    assert attributes == {"repo": "app", "tier": "unit-test", "outcome": "open"}
    assert value >= 0


def test_the_review_rounds_of_a_unit_go_through_the_helper(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],
) -> None:
    ticks.recorder.verdicts = [rejecting("rename the lock")]
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.agents()

    ticks.tick()

    assert named(emitted, "abk.review.rounds") == [
        (
            "observe",
            "abk.review.rounds",
            2,
            UNIT,
            "add-marker",
            {"repo": "app", "outcome": "open"},
        )
    ]
