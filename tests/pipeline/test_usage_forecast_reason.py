"""A refusal for the forecast says why: the estimate's text, the window, the forecast in points
and the role, node and round (or reservation) with the most points, and the prior when it was
used; the unit is stopped as any refusal stops it (spec: usage-pause)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.usage_forecast_fixtures import Fixture, spec_history
from tests.usage_forecast_gate import ask, held, keep_timer, lay, lay_calls, live
from tests.usage_host import Host

AUTO, FULL = ReviewTier.AUTO, ReviewTier.FULL


def test_the_reason_holds_the_estimate_the_window_the_forecast_and_the_largest_part(
    host: Host,
) -> None:
    held(host, session=67.0)
    lay(host, spec_history())

    reason = ask(FULL).reason

    assert "session ~67% estimated (67% read + 0% spent" in reason
    assert "session" in reason.split("forecast", 1)[-1]
    assert "8.6" in reason
    assert "review round 1" in reason
    assert "largest" in reason


def test_the_reason_names_a_reservation_when_it_is_the_largest(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A health track reserving 5 points against a unit forecast at 3: 70 plus 5 plus 3 plus 5
    is not under 80, where without the track 70 plus 3 plus 5 is."""
    held(host, session=70.0)
    history = Fixture()
    history.units(20, AUTO, [("implement", 0, 1.2)])
    lay(host, history)
    lay_calls(host, "track_health", 2.0)
    keep_timer(host, tmp_path, monkeypatch, track="health", fires_in=timedelta(hours=1))

    reason = ask(AUTO).reason

    assert "track_health" in reason
    assert "largest" in reason


def test_a_track_that_proposes_reserves_its_propose_call_too(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An improve track at 1 point is reserved beside a unit at 3: 70 plus 3 plus 1 plus 5 is
    under 80, and adding the 5 points of the propose call it goes on to make is not."""
    held(host, session=70.0)
    history = Fixture()
    history.units(20, AUTO, [("implement", 0, 1.2)])
    lay(host, history)
    lay_calls(host, "track_improve", 0.4)
    keep_timer(host, tmp_path, monkeypatch, track="improve", fires_in=timedelta(hours=1))

    assert ask(AUTO).may_start

    lay_calls(host, "track_propose", 2.0)
    refusal = ask(AUTO)

    assert not refusal.may_start
    assert "track_propose reservation" in refusal.reason


def test_a_track_s_refusal_names_its_step_and_not_a_unit(host: Host) -> None:
    held(host, session=67.0)
    lay_calls(host, "track_health", 4.0)

    refusal = ask(None, "track:health", step="track_health")

    assert refusal.reason.count("unit track:health") == 0
    assert "track_health forecast" in refusal.reason


def test_a_refusal_on_a_live_reading_is_not_called_an_estimate(host: Host) -> None:
    live(host, session=70.0)
    lay(host, spec_history())

    refusal = ask(FULL)

    assert not refusal.may_start
    assert "estimated" not in refusal.reason
    assert "session 70% read + " in refusal.reason


def test_the_reason_says_when_the_prior_was_used(host: Host) -> None:
    """Five `full` units are under the minimum of six, so a `full` unit is forecast at the
    window's flat allowance of 17 points: 67 plus 17 plus 5 is not under 80."""
    held(host, session=67.0)
    history = Fixture()
    history.units(5, FULL, [("review", 1, 1.0)])
    lay(host, history)

    refusal = ask(FULL)

    assert not refusal.may_start
    assert "prior" in refusal.reason


def test_the_refused_unit_is_stopped_with_its_resume_time(host: Host) -> None:
    held(host, session=67.0)
    lay(host, spec_history())
    may_start, resume_at = build_usage_gate(start=lambda: ask(FULL, "full/1"))

    allowed, reason = may_start()
    until = resume_at()

    assert not allowed
    assert "forecast" in reason
    assert until is not None
    assert until > datetime.now(UTC)
