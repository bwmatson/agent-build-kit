"""The one function that sends a metric to telemetry and records it locally
(spec: dry-cleanup, a metric with a local record is emitted through one function)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_build_kit import config, telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.metric_records import (
    InstrumentKind,
    MetricRecord,
    emit_metric,
    read_metrics,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME

Sent = list[tuple[str, str, float, dict[str, Any]]]


def ledger_records() -> list[MetricRecord]:
    root = config.active_root()
    assert root is not None
    return read_metrics(Installation(config.active(), root).state_dir / LEDGER_NAME)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Sent:
    """What telemetry was asked to send, by instrument kind."""
    calls: Sent = []

    def spy(instrument: str) -> Callable[..., None]:
        def send(name: str, value: float = 1, **attributes: Any) -> None:
            calls.append((instrument, name, value, attributes))

        return send

    for instrument in ("count", "duration", "observe", "level"):
        monkeypatch.setattr(telemetry, instrument, spy(instrument))
    return calls


# The six sites' shapes: the instrument, the name, the value and what each carried.
SITES = [
    ("duration", "abk.tick.duration", 12.5, {"outcome": "built"}, "", ""),
    ("count", "abk.usage.pauses", 1, {"kind": "usage"}, "", ""),
    (
        "duration",
        "abk.unit.duration",
        30.25,
        {"repo": "app", "tier": "tier1", "outcome": "open"},
        "feature/1",
        "feature",
    ),
    ("count", "abk.usage.pauses", 1, {"kind": "rate_limit"}, "feature/1", "feature"),
    ("count", "abk.usage.pauses", 1, {"kind": "usage"}, "feature/1", "feature"),
    (
        "observe",
        "abk.review.rounds",
        2,
        {"repo": "app", "outcome": "satisfied"},
        "feature/1",
        "feature",
    ),
]


@pytest.mark.parametrize(("instrument", "name", "value", "attributes", "unit", "change"), SITES)
def test_telemetry_and_the_local_record_get_the_same_name_value_and_attributes(
    sent: Sent,
    instrument: InstrumentKind,
    name: str,
    value: float,
    attributes: dict[str, Any],
    unit: str,
    change: str,
) -> None:
    told: list[str] = []

    emit_metric(instrument, name, value, told.append, unit=unit, change=change, **attributes)

    assert sent == [(instrument, name, value, attributes)]
    (record,) = ledger_records()
    assert (record.metric, record.value, record.attributes) == (name, value, attributes)
    assert (record.unit, record.change) == (unit, change)
    assert told == []


def test_a_level_is_sent_as_a_level(sent: Sent) -> None:
    emit_metric("level", "abk.slots.free", 3, lambda line: None, state="idle")

    assert sent == [("level", "abk.slots.free", 3, {"state": "idle"})]
    assert [r.metric for r in ledger_records()] == ["abk.slots.free"]


def test_with_telemetry_off_the_record_is_still_written() -> None:
    emit_metric("count", "abk.usage.pauses", 1, lambda line: None, unit="feature/1", kind="usage")

    (record,) = ledger_records()
    assert (record.metric, record.value, record.attributes) == (
        "abk.usage.pauses",
        1,
        {"kind": "usage"},
    )
    assert record.unit == "feature/1"


def test_the_unit_and_change_reach_the_record_only_never_telemetry(sent: Sent) -> None:
    emit_metric("count", "abk.usage.pauses", 1, lambda line: None, unit="u/1", change="c", kind="x")

    ((_, _, _, attributes),) = sent
    assert attributes == {"kind": "x"}
