"""The forecast leaves the emergency lane and the cap on starts as they were: usage reads no
priority, a lane unit that is running is a running unit, and a start the forecast refuses is not
one the cap counts (spec: usage-pause).

The gate is the real one (`build_usage_gate`), asked as the runner asks it, in `starting`."""

import json
from datetime import UTC, datetime

import pytest

from agent_build_kit.pipeline.usage_forecast_record import FORECASTS_NAME, StepRow, record_admission
from agent_build_kit.pipeline.usage_guard import starting
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.factories import stored_unit
from tests.usage_cost_estimate import MINUTE, admit, row
from tests.usage_forecast_fixtures import Fixture, spec_history
from tests.usage_forecast_gate import held, lay
from tests.usage_host import Host

AUTO, FULL = ReviewTier.AUTO, ReviewTier.FULL


def gate(uid: str, tier: ReviewTier, *, priority: int = 3) -> tuple[bool, str]:
    """The answer of the gate before the first step of a unit of `priority` and `tier`."""
    unit = stored_unit(uid, change=uid.partition("/")[0], priority=priority, review_tier=tier)
    may_start, _ = build_usage_gate()
    with starting(unit.id, review_tier=tier, estimated_lines=unit.estimated_lines):
        return may_start()


@pytest.mark.parametrize("priority", [0, 3])
def test_a_unit_of_any_priority_is_refused_or_allowed_by_its_forecast(
    host: Host, priority: int
) -> None:
    held(host, session=67.0)
    lay(host, spec_history())

    full, why = gate("feature/1", FULL, priority=priority)
    auto, _ = gate("feature/2", AUTO, priority=priority)

    assert not full
    assert "forecast" in why
    assert auto


def test_a_lane_unit_that_is_running_is_a_running_unit_for_another_s_forecast(
    host: Host,
) -> None:
    """The running unit's review round 1 has $1.00 left: 70 plus its 2.5 points plus the asking
    unit's 2.5 plus 5 is not under 80, where 70 plus 2.5 plus 5 is."""
    held(host, session=70.0)
    history = Fixture()
    history.units(20, AUTO, [("review", 1, 1.0)])
    lay(host, history)
    lane = stored_unit("lane/1", change="lane", priority=0, review_tier=AUTO)
    admit(host, lane.id)
    started = StepRow(unit=lane.id, node="review", round=1, at=datetime.now(UTC) - 4 * MINUTE)
    record_admission(
        host.cache.parent / FORECASTS_NAME, started, None, enabled=True, say=pytest.fail
    )

    allowed, why = gate("feature/1", AUTO)

    assert not allowed
    assert "forecast" in why


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])


def spent(host: Host, *units: str) -> None:
    """`units` admitted on the estimate, each with a ledger row of $0.10 since the reading."""
    admit(host, *units)
    for unit in units:
        row(host, "implement", 0.1, unit=unit)


def test_with_three_admitted_a_fourth_that_fits_is_refused_for_the_cap(host: Host) -> None:
    held(host, session=67.0, usage_estimate_max_starts=3)
    lay(host, spec_history())
    spent(host, "a/1", "a/2", "a/3")

    full, forecast = gate("feature/1", FULL)
    auto, cap = gate("feature/2", AUTO)

    assert not full
    assert "forecast" in forecast
    assert not auto
    assert "3 starts have been made" in cap
    assert admitted(host) == ["a/1", "a/2", "a/3"]


def test_a_unit_the_forecast_refused_does_not_count_towards_the_cap(host: Host) -> None:
    held(host, session=67.0, usage_estimate_max_starts=3)
    lay(host, spec_history())
    spent(host, "a/1", "a/2")

    full, why = gate("feature/1", FULL)
    auto, _ = gate("feature/2", AUTO)

    assert not full
    assert "forecast" in why
    assert auto
    assert admitted(host) == ["a/1", "a/2", "feature/2"]
