"""A start is refused for a window when its estimate plus the forecast and the margin is not
under the threshold, on an estimate and on a live reading (spec: usage-pause).

Only the endpoint and the home directory are faked (`tests/usage_host.py`); the history is the
real ledger and verdict file beside the cache. A unit admitted on an estimate is counted by the
asks after it, so each test asks for the unit it expects refused first."""

import pytest

from agent_build_kit.pipeline.usage_guard import decide_start
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.settings import settings
from tests.usage_forecast_fixtures import Fixture, spec_history
from tests.usage_forecast_gate import EXACT, ask, held, keep_points, lay, live
from tests.usage_host import Host, configure

AUTO, FULL, LIGHT = ReviewTier.AUTO, ReviewTier.FULL, ReviewTier.LIGHT


def test_on_an_estimate_an_auto_unit_is_allowed_and_a_full_unit_refused(host: Host) -> None:
    """67 plus 6.4 plus 5 is under 80, and 67 plus 8.6 plus 5 is not."""
    held(host, session=67.0)
    lay(host, spec_history())

    refusal = ask(FULL, "full/1")
    allowed = ask(AUTO, "auto/1")

    assert not refusal.may_start
    assert "session ~67% estimated" in refusal.reason
    assert allowed.may_start


def test_on_a_live_reading_a_full_unit_is_refused_and_an_auto_unit_allowed(host: Host) -> None:
    live(host, session=67.0)
    lay(host, spec_history())

    refusal = ask(FULL, "full/1")
    allowed = ask(AUTO, "auto/1")

    assert not refusal.may_start
    assert "forecast" in refusal.reason
    assert allowed.may_start


def test_a_full_unit_the_reading_alone_allows_is_refused_for_its_forecast(host: Host) -> None:
    live(host, session=70.0)
    lay(host, spec_history())

    refusal = ask(FULL)

    assert not refusal.may_start
    assert "session" in refusal.reason
    assert "forecast" in refusal.reason


def test_a_forecast_of_zero_adds_nothing_and_a_unit_with_a_cost_is_refused(host: Host) -> None:
    """A tier whose recorded calls cost nothing is left to the estimate, which leaves room;
    a tier with a cost is refused for the points that room does not hold."""
    held(host, session=74.0)
    history = spec_history()
    history.units(20, LIGHT, [("review", 1, 0.0)])
    lay(host, history)

    refusal = ask(FULL, "full/1")
    allowed = ask(LIGHT, "light/1")

    assert not refusal.may_start
    assert "forecast" in refusal.reason
    assert allowed.may_start


def test_a_refusal_on_the_estimate_itself_is_as_before_when_the_forecast_is_zero(
    host: Host,
) -> None:
    held(host, session=77.0)
    history = spec_history()
    history.units(20, LIGHT, [("review", 1, 0.0)])
    lay(host, history)

    unforecast = decide_start()
    zero = ask(LIGHT, "light/1")
    costly = ask(FULL, "full/1")

    assert not zero.may_start
    assert zero.reason == unforecast.reason
    assert zero.resume_at == unforecast.resume_at
    assert "is not 5 points under 80%" in costly.reason
    assert "forecast" in costly.reason


def test_a_weekly_estimate_under_its_threshold_refuses_a_unit_forecast_at_two_weekly_points(
    host: Host,
) -> None:
    """86 plus the margin of 5 is under 92, and with two points more it is not; the session
    window has room."""
    held(host, session=10.0, weekly=86.0, weekly_pause=92)
    keep_points(host, session=1.0, weekly=1.0)
    history = Fixture()
    history.units(20, AUTO, [("implement", 0, 2.0)])
    lay(host, history)

    refusal = ask(AUTO)

    assert not refusal.may_start
    assert "weekly" in refusal.reason
    assert "is not 5 points under 92%" in refusal.reason


def test_with_the_forecast_off_the_decision_is_what_it_was(host: Host) -> None:
    held(host, session=67.0)
    lay(host, spec_history())
    assert not ask(FULL, "full/1").may_start

    configure(
        session={"usage_pause_pct": 80},
        weekly={"usage_pause_pct": 80},
        usage_climb_floor=2.0,
        usage_forecast=False,
        **EXACT,
    )

    assert ask(FULL, "full/2").may_start


def test_with_the_guard_off_a_start_is_allowed(host: Host, monkeypatch: pytest.MonkeyPatch) -> None:
    held(host, session=67.0)
    lay(host, spec_history())
    assert not ask(FULL, "full/1").may_start

    monkeypatch.setattr(settings, "usage_guard", "off")

    allowed = ask(FULL, "full/2")

    assert allowed.may_start
    assert allowed.source == "off"
