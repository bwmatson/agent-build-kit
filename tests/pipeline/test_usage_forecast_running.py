"""A unit running a step adds the unfinished share of that step's expected cost, and replaces the
flat allowance the estimate counts for an admitted unit with no ledger row (spec: usage-pause)."""

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.usage_forecast_record import FORECASTS_NAME, StepRow
from agent_build_kit.pipeline.usage_forecast_running import running_remainders
from agent_build_kit.pipeline.usage_guard import decide_start
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, append_record
from tests.usage_cost_estimate import HOUR, admit, cost_fit, keep_fits, paused
from tests.usage_forecast_fixtures import call
from tests.usage_host import Host

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def history(*, at: datetime = NOW - 3 * HOUR) -> list[UsageRecord]:
    """Two review round 1 calls of other units, $1.00 and ten minutes each."""
    return [
        call(f"old{n}/1", "review", 1, 1.0, duration_ms=600_000, at=at.isoformat())
        for n in range(2)
    ]


def started(ago: timedelta, unit: str = "feature/1") -> StepRow:
    return StepRow(unit=unit, node="review", round=1, at=NOW - ago)


def remainders(
    steps: list[StepRow],
    records: list[UsageRecord],
    *,
    running: tuple[str, ...] = ("feature/1",),
    asking: str | None = "feature/9",
):
    return running_remainders(
        steps, records, running=running, asking=asking, now=NOW, points_per_usd=2.5
    )


def test_a_step_four_minutes_into_ten_adds_what_is_left_of_it() -> None:
    found = remainders([started(4 * MINUTE)], history())

    [only] = found.running
    assert (only.unit, only.node, only.round) == ("feature/1", "review", 1)
    assert only.usd == pytest.approx(0.6)
    assert only.points == pytest.approx(1.5)


def test_a_step_past_its_mean_duration_adds_a_tenth() -> None:
    [only] = remainders([started(20 * MINUTE)], history()).running

    assert only.usd == pytest.approx(0.1)


def test_a_step_with_a_later_ledger_row_of_the_unit_adds_nothing() -> None:
    ended = call("feature/1", "review", 1, 1.0, at=(NOW - MINUTE).isoformat())

    found = remainders([started(4 * MINUTE)], [*history(), ended])

    assert found.running == ()
    assert found.unrecorded == 0


def test_the_unit_asking_is_not_counted() -> None:
    steps = [started(4 * MINUTE), started(2 * MINUTE, "feature/2")]

    found = remainders(steps, history(), running=("feature/1", "feature/2"), asking="feature/1")

    assert [r.unit for r in found.running] == ["feature/2"]


def test_the_latest_step_row_of_a_unit_is_the_step_it_runs() -> None:
    earlier = StepRow(unit="feature/1", node="tests", round=0, at=NOW - 30 * MINUTE)
    ended = call("feature/1", "tests", 0, 1.0, at=(NOW - 25 * MINUTE).isoformat())

    found = remainders([earlier, started(4 * MINUTE)], [*history(), ended])

    assert [(r.node, r.round) for r in found.running] == [("review", 1)]


def test_a_running_unit_with_no_step_row_adds_nothing_and_is_counted() -> None:
    found = remainders([], history(), running=("feature/1", "feature/2"))

    assert found.running == ()
    assert found.unrecorded == 2


def test_an_admitted_unit_with_a_step_row_is_not_also_counted_at_the_flat_allowance(
    host: Host,
) -> None:
    paused(host, session=61.0)
    keep_fits(host, session=cost_fit(2.65, flat=17))
    for row in history(at=datetime.now(UTC) - 3 * HOUR):
        append_record(host.cache.parent / LEDGER_NAME, row)
    admit(host, "feature/1", "feature/2")
    append_record(
        host.cache.parent / FORECASTS_NAME,
        StepRow(unit="feature/1", node="review", round=1, at=datetime.now(UTC) - 4 * MINUTE),
    )

    decision = decide_start(unit="feature/3")

    # feature/1 adds its 0.6 of $1.00 at 2.65 points, feature/2 with no step row the flat 17.
    assert "session ~80% estimated (61% read + 19% spent" in decision.reason
    assert "1 unit not yet recorded" in decision.reason


def test_a_unit_whose_step_has_no_costed_history_is_still_counted_at_the_flat_allowance(
    host: Host,
) -> None:
    paused(host, session=61.0)
    keep_fits(host, session=cost_fit(2.65, flat=17))
    for row in history(at=datetime.now(UTC) - 3 * HOUR):
        append_record(host.cache.parent / LEDGER_NAME, row)
    admit(host, "feature/1", "feature/2")
    for unit in ("feature/1", "feature/2"):
        append_record(
            host.cache.parent / FORECASTS_NAME,
            StepRow(unit=unit, node="review", round=2, at=datetime.now(UTC) - 4 * MINUTE),
        )

    decision = decide_start(unit="feature/3")

    assert "2 units not yet recorded" in decision.reason


def test_a_ledger_row_whose_time_does_not_parse_is_skipped() -> None:
    odd = call("feature/1", "review", 1, 1.0, at="not a time")

    [only] = remainders([started(4 * MINUTE)], [*history(), odd]).running

    assert only.usd == pytest.approx(0.6)
