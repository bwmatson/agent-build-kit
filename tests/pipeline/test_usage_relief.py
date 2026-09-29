"""The threshold ramp: running a window fuller the closer its reset is.

Quota left over when a window resets is gone, and the reasons the flat 70%
existed — room for units already running, room for the user's own sessions —
shrink as the reset approaches. So the threshold rises to a ceiling below the
credits line, per window, against that window's own reset.

The arithmetic is here; `test_usage_guard.py` covers the pause rules the ramp
plugs into, and nothing in either file touches the network or a real clock.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig
from agent_build_kit.pipeline.usage_guard import (
    MAX_SCHEDULED_PAUSE,
    RESUME_GRACE,
    SESSION_WINDOW,
    WEEKLY_WINDOW,
    Limits,
    UsageReading,
    Window,
    may_start_unit,
    relief_at,
    threshold_at,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
LIMITS = Limits(pause_pct=70, ceiling_pct=90, relief_fraction=0.25, resume_buffer_pct=5)

# A quarter of five hours: the ramp covers the last 75 minutes of a session.
SESSION_SPAN = SESSION_WINDOW * LIMITS.relief_fraction


def session(*, used: int = 10, resets_in: timedelta | None = SESSION_SPAN * 2) -> Window:
    return Window(
        name="session",
        used_pct=used,
        resets_at=None if resets_in is None else NOW + resets_in,
        length=SESSION_WINDOW,
    )


def weekly(*, used: int = 10, resets_in: timedelta = timedelta(days=3)) -> Window:
    return Window(name="weekly", used_pct=used, resets_at=NOW + resets_in, length=WEEKLY_WINDOW)


def reading(
    *,
    session_pct: int = 10,
    weekly_pct: int = 10,
    resets_in: timedelta = timedelta(hours=3),
    weekly_resets_in: timedelta = timedelta(days=3),
) -> UsageReading:
    now = datetime.now(UTC)
    return UsageReading(
        session_pct=session_pct,
        weekly_pct=weekly_pct,
        resets_at=now + resets_in,
        weekly_resets_at=now + weekly_resets_in,
        observed_at=now,
        source="live",
        credits_enabled=False,
        credits_used_dollars=0.0,
        spend_limit_reached=False,
    )


# --- the ramp ------------------------------------------------------------------


def test_most_of_a_window_keeps_the_configured_floor() -> None:
    """Relief is for the end of a window. Earlier on, nothing changes."""
    assert threshold_at(session(resets_in=timedelta(hours=4)), now=NOW, limits=LIMITS) == 70
    # Including the moment the ramp is about to begin.
    assert threshold_at(session(resets_in=SESSION_SPAN), now=NOW, limits=LIMITS) == 70


def test_the_threshold_rises_as_the_reset_nears() -> None:
    halfway = threshold_at(session(resets_in=SESSION_SPAN / 2), now=NOW, limits=LIMITS)
    nearly = threshold_at(session(resets_in=SESSION_SPAN / 10), now=NOW, limits=LIMITS)

    assert halfway == 80
    assert 80 < nearly < 90


def test_the_ceiling_is_reached_at_the_reset_and_never_passed() -> None:
    """The ceiling is what keeps relief clear of the credits line: past 100%
    the account pays cash, so the ramp must stop well short of it."""
    assert threshold_at(session(resets_in=timedelta(0)), now=NOW, limits=LIMITS) == 90
    # A reset in the past — a reading taken just before the boundary — is
    # still the ceiling, not something above it.
    assert threshold_at(session(resets_in=-timedelta(minutes=5)), now=NOW, limits=LIMITS) == 90


def test_a_window_that_is_not_open_gets_the_floor() -> None:
    """`resets_at: null` means nothing has been used since the last window
    ended. There is no reset approaching, so there is nothing to relieve."""
    assert threshold_at(session(resets_in=None), now=NOW, limits=LIMITS) == 70


def test_each_window_ramps_against_its_own_reset() -> None:
    """A session minutes from resetting says nothing about the week, and a
    week about to roll over says nothing about the session."""
    fresh_session_late_week = reading(
        session_pct=75,
        weekly_pct=75,
        resets_in=timedelta(hours=4),
        weekly_resets_in=timedelta(hours=2),
    )

    decision = may_start_unit(fresh_session_late_week)

    # The weekly window is deep in its ramp (90%), the session is not (70%),
    # so the session is what refuses — the opposite of the flat rule, where
    # the weekly number would have been just as blocking.
    assert not decision.may_start
    assert decision.reason.startswith("session usage at 75%")


# --- what the ramp lets through ------------------------------------------------


def test_a_unit_starts_near_a_reset_that_would_have_paused_earlier() -> None:
    """The point of the change: 78% is over the floor and under the ramp."""
    assert not may_start_unit(reading(session_pct=78, resets_in=timedelta(hours=3))).may_start
    assert may_start_unit(reading(session_pct=78, resets_in=timedelta(minutes=20))).may_start


def test_relief_never_reaches_the_credits_backstops() -> None:
    """Credits are the user's reserve. However close a reset is, a window at
    100% with credits enabled still stops."""
    full = reading(session_pct=100, resets_in=timedelta(minutes=1)).model_copy(
        update={"credits_enabled": True}
    )

    decision = may_start_unit(full)

    assert not decision.may_start
    assert "credits" in decision.reason


def test_a_stale_reading_is_still_unusable_next_to_a_reset() -> None:
    """The ramp trusts the reading; it does not make a bad one good."""
    stale = reading(session_pct=10, resets_in=timedelta(minutes=5)).model_copy(
        update={"source": "claude.json", "observed_at": datetime.now(UTC) - timedelta(hours=6)}
    )

    assert not may_start_unit(stale).may_start
    assert "stale" in may_start_unit(stale).reason


# --- when to look again --------------------------------------------------------


def test_the_resume_waits_for_room_to_work_not_just_for_the_threshold() -> None:
    """Waking when the threshold merely equals current usage would start a
    unit with nothing left to finish on. The buffer is that room."""
    window = session(used=74, resets_in=SESSION_SPAN)

    resume = relief_at(window, now=NOW, limits=LIMITS)

    assert resume is not None
    # 74 + 5 = 79%, which the ramp reaches 45% of the way through the span.
    assert resume == NOW + SESSION_SPAN * 0.45


def test_a_window_the_ramp_can_never_clear_waits_for_the_reset() -> None:
    """99% is above the ceiling, so no amount of waiting inside this window
    opens it: the reset itself is the next thing that can change."""
    assert relief_at(session(used=99, resets_in=timedelta(hours=2)), now=NOW, limits=LIMITS) is None

    decision = may_start_unit(reading(session_pct=99, resets_in=timedelta(hours=2)))

    assert not decision.may_start
    assert decision.resume_after_seconds == pytest.approx(
        (timedelta(hours=2) + RESUME_GRACE).total_seconds(), abs=5
    )


def test_no_pause_is_scheduled_further_out_than_the_recheck_cap() -> None:
    """A weekly window can reset days away, and `pause_until` never shortens
    an existing pause — an honest wait would sleep through everything."""
    decision = may_start_unit(reading(weekly_pct=99, weekly_resets_in=timedelta(days=5)))

    assert not decision.may_start
    assert decision.reason.startswith("weekly")
    assert decision.resume_after_seconds <= MAX_SCHEDULED_PAUSE.total_seconds()


def test_the_reason_says_what_the_threshold_is_doing() -> None:
    """`abk status` and paused.json are the only account of why work stopped,
    and a moving threshold is unexplainable without the number it is heading
    for."""
    decision = may_start_unit(reading(session_pct=82, resets_in=timedelta(minutes=30)))

    assert not decision.may_start
    assert "session usage at 82%" in decision.reason
    assert "ramping to 90%" in decision.reason


def test_a_started_unit_reports_both_thresholds() -> None:
    decision = may_start_unit(reading(session_pct=20, weekly_pct=30))

    assert decision.may_start
    assert "session 70%" in decision.reason and "weekly 70%" in decision.reason


# --- configuration -------------------------------------------------------------


def test_a_ceiling_below_the_floor_is_refused() -> None:
    """It would make the threshold *fall* towards a reset, which no caller
    would ever be able to explain."""
    with pytest.raises(ValidationError):
        LimitsConfig(usage_pause_pct=80, usage_ceiling_pct=70)


def test_the_ceiling_stays_under_the_credits_line() -> None:
    with pytest.raises(ValidationError):
        LimitsConfig(usage_ceiling_pct=100)
