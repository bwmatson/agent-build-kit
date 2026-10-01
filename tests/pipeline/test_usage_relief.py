"""The threshold ramp: running a window fuller the closer its reset is.

Quota left over when a window resets is gone, and the reasons the flat 70%
existed — room for units already running, room for the user's own sessions —
shrink as the reset approaches. So the threshold rises to a ceiling below the
credits line, per window, against that window's own reset.

The arithmetic is here; `test_usage_guard.py` covers the pause rules the ramp
plugs into, and nothing in either file touches the network or a real clock.

Each window has its own pause percent and ceiling, under `runtimes.claude_code`.
A ceiling left out is the pause percent, and a window whose two are equal does
not ramp at all.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_build_kit import config as config_module
from agent_build_kit.config import (
    CLAUDE_CODE,
    ClaudeLimitsConfig,
    RuntimeConfig,
    UsageWindowConfig,
    WorkspaceConfig,
)
from agent_build_kit.pipeline.usage_guard import (
    MAX_SCHEDULED_PAUSE,
    RESUME_GRACE,
    SESSION_WINDOW,
    WEEKLY_WINDOW,
    Band,
    Limits,
    UsageReading,
    Window,
    may_start_unit,
    relief_at,
    threshold_at,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def limits(
    *,
    session: tuple[int, int] = (70, 90),
    weekly: tuple[int, int] = (70, 90),
    relief: tuple[float, float] = (0.25, 0.25),
    buffer: tuple[int, int] = (5, 5),
) -> Limits:
    """(pause, ceiling) for each window, and each window's relief fraction and
    resume buffer."""
    return Limits(
        session=Band(
            pause_pct=session[0],
            ceiling_pct=session[1],
            relief_fraction=relief[0],
            resume_buffer_pct=buffer[0],
        ),
        weekly=Band(
            pause_pct=weekly[0],
            ceiling_pct=weekly[1],
            relief_fraction=relief[1],
            resume_buffer_pct=buffer[1],
        ),
    )


LIMITS = limits()


def configure(
    session: dict[str, object] | None = None, weekly: dict[str, object] | None = None
) -> None:
    """Make these the Claude runtime's limits for `may_start_unit`, which reads
    the active config. Each argument is one window's section. The suite's
    autouse fixture resets the config afterwards."""
    limits_block = {"session": session or {}, "weekly": weekly or {}}
    config_module.activate(
        WorkspaceConfig.model_validate({"runtimes": {CLAUDE_CODE: {"limits": limits_block}}}),
        None,
    )


@pytest.fixture(autouse=True)
def ramp_70_to_90() -> None:
    """The ramp these tests are about, spelled out: it is not the default."""
    ramp: dict[str, object] = {"usage_pause_pct": 70, "usage_pause_ceiling_pct": 90}
    configure(session=ramp, weekly=ramp)


# A quarter of five hours: the ramp covers the last 75 minutes of a session.
SESSION_SPAN = SESSION_WINDOW * LIMITS.session.relief_fraction


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
    """A weekly window can reset days away: an honest wait would put the
    marker's deadline days out, and `abk status` would say so."""
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


# --- a window that does not ramp ----------------------------------------------


def test_equal_pause_and_ceiling_skip_the_ramp() -> None:
    """The threshold is the one number all the way to the reset, including the
    moment the ramp would have begun and the moment of the reset itself."""
    flat = limits(session=(85, 85))

    for resets_in in (timedelta(hours=4), SESSION_SPAN, SESSION_SPAN / 2, timedelta(0)):
        assert threshold_at(session(resets_in=resets_in), now=NOW, limits=flat) == 85


def test_a_flat_window_offers_no_relief_before_its_reset() -> None:
    """Nothing inside the window can raise a threshold that does not move, so
    only the reset can bring room back. (No division by a zero-width ramp.)"""
    flat = limits(session=(85, 85))

    assert relief_at(session(used=88, resets_in=SESSION_SPAN / 2), now=NOW, limits=flat) is None
    # Room that is already there is still room.
    assert relief_at(session(used=70, resets_in=SESSION_SPAN / 2), now=NOW, limits=flat) == NOW


def test_a_flat_window_does_not_claim_to_be_ramping() -> None:
    configure(session={"usage_pause_pct": 80}, weekly={"usage_pause_pct": 80})

    decision = may_start_unit(reading(session_pct=82, resets_in=timedelta(minutes=30)))

    assert not decision.may_start
    assert "session usage at 82%" in decision.reason
    assert "threshold 80%" in decision.reason
    assert "ramping" not in decision.reason


def test_a_flat_window_stays_flat_next_to_its_reset() -> None:
    """The case the ramp exists for: 78% twenty minutes from a reset. Flat at
    75, it still refuses."""
    configure(session={"usage_pause_pct": 75}, weekly={"usage_pause_pct": 75})

    assert not may_start_unit(reading(session_pct=78, resets_in=timedelta(minutes=20))).may_start


# --- the two windows are separate ----------------------------------------------


def test_the_session_can_ramp_while_the_week_does_not() -> None:
    mixed = limits(session=(70, 90), weekly=(80, 80))
    near = SESSION_SPAN / 2

    assert threshold_at(session(resets_in=near), now=NOW, limits=mixed) == 80
    assert threshold_at(weekly(resets_in=timedelta(hours=1)), now=NOW, limits=mixed) == 80
    assert threshold_at(weekly(resets_in=timedelta(days=3)), now=NOW, limits=mixed) == 80


def test_each_window_has_its_own_pause_percent() -> None:
    configure(session={"usage_pause_pct": 60}, weekly={"usage_pause_pct": 90})

    assert not may_start_unit(reading(session_pct=65, weekly_pct=10)).may_start
    assert may_start_unit(reading(session_pct=10, weekly_pct=85)).may_start
    assert not may_start_unit(reading(session_pct=10, weekly_pct=92)).may_start


def test_a_ceiling_on_one_window_does_not_move_the_other() -> None:
    configure(session={"usage_pause_pct": 70, "usage_pause_ceiling_pct": 90})

    session_late = reading(session_pct=78, resets_in=timedelta(minutes=20))
    week_late = reading(weekly_pct=78, weekly_resets_in=timedelta(minutes=20))

    assert may_start_unit(session_late).may_start
    assert not may_start_unit(week_late).may_start


def test_the_defaults_pause_both_windows_at_seventy_with_no_ramp() -> None:
    configure()

    decision = may_start_unit(reading(session_pct=70, resets_in=timedelta(minutes=1)))

    assert not decision.may_start
    assert "threshold 70%" in decision.reason and "ramping" not in decision.reason


# --- relief fraction and resume buffer are per window --------------------------


def test_each_window_ramps_over_its_own_trailing_fraction() -> None:
    """A quarter of a week is ~42 hours; a quarter of a session is ~75 minutes.
    A caller who wants the week to ramp over its last 6 hours says so."""
    short_week = limits(relief=(0.25, 6 / 168))

    assert threshold_at(weekly(resets_in=timedelta(hours=6)), now=NOW, limits=short_week) == 70
    assert threshold_at(weekly(resets_in=timedelta(hours=6)), now=NOW, limits=LIMITS) > 85


def test_the_session_fraction_does_not_move_the_week() -> None:
    wide_session = limits(relief=(1.0, 0.25))

    assert threshold_at(session(resets_in=SESSION_WINDOW / 2), now=NOW, limits=wide_session) == 80
    assert threshold_at(weekly(resets_in=timedelta(days=3)), now=NOW, limits=wide_session) == 70


def test_each_window_waits_for_its_own_resume_buffer() -> None:
    """At 66% used the base (70%) already leaves room for a buffer of 0, but a
    buffer of 5 wants 71% and must wait for the ramp to offer it."""
    roomy = limits(buffer=(0, 5))

    no_wait = relief_at(session(used=66, resets_in=SESSION_SPAN), now=NOW, limits=roomy)
    waits = relief_at(weekly(used=66, resets_in=timedelta(days=3)), now=NOW, limits=roomy)

    assert no_wait == NOW
    assert waits is not None and waits > NOW


def test_configured_limits_carry_each_windows_own_numbers() -> None:
    configure(
        session={"usage_relief_fraction": 0.5, "usage_resume_buffer_pct": 2},
        weekly={"usage_relief_fraction": 0.1, "usage_resume_buffer_pct": 9},
    )

    configured = Limits.configured()

    assert (configured.session.relief_fraction, configured.session.resume_buffer_pct) == (0.5, 2)
    assert (configured.weekly.relief_fraction, configured.weekly.resume_buffer_pct) == (0.1, 9)


# --- configuration -------------------------------------------------------------


def test_the_two_windows_have_the_same_settings_under_the_same_names() -> None:
    claude = ClaudeLimitsConfig()

    assert type(claude.session) is type(claude.weekly) is UsageWindowConfig
    assert set(UsageWindowConfig.model_fields) == {
        "usage_pause_pct",
        "usage_pause_ceiling_pct",
        "usage_relief_fraction",
        "usage_resume_buffer_pct",
    }


def test_a_ceiling_left_out_is_the_pause_percent() -> None:
    window = UsageWindowConfig(usage_pause_pct=82)

    assert window.usage_ceiling_pct == 82
    assert window.usage_pause_ceiling_pct is None


def test_a_ceiling_below_the_pause_percent_is_refused() -> None:
    """It would make the threshold *fall* towards a reset, which no caller
    would ever be able to explain. Each window is checked on its own."""
    with pytest.raises(ValidationError, match="usage_pause_ceiling_pct"):
        UsageWindowConfig(usage_pause_pct=80, usage_pause_ceiling_pct=70)
    with pytest.raises(ValidationError, match=r"limits\.weekly"):
        WorkspaceConfig.model_validate(
            {
                "runtimes": {
                    CLAUDE_CODE: {
                        "limits": {"weekly": {"usage_pause_pct": 80, "usage_pause_ceiling_pct": 70}}
                    }
                }
            }
        )


def test_a_ceiling_with_no_pause_percent_is_checked_against_the_default() -> None:
    with pytest.raises(ValidationError):
        UsageWindowConfig(usage_pause_ceiling_pct=60)


@pytest.mark.parametrize("field", ["usage_pause_pct", "usage_pause_ceiling_pct"])
def test_the_credits_line_is_never_reached(field: str) -> None:
    with pytest.raises(ValidationError):
        UsageWindowConfig.model_validate({field: 100})


@pytest.mark.parametrize("fraction", [0, -0.1, 1.5])
def test_a_relief_fraction_outside_zero_to_one_is_refused(fraction: float) -> None:
    with pytest.raises(ValidationError):
        UsageWindowConfig(usage_relief_fraction=fraction)


def test_an_unknown_setting_in_a_window_is_refused() -> None:
    """A misspelling must not read as a limit that is not there."""
    with pytest.raises(ValidationError):
        UsageWindowConfig.model_validate({"usage_pause_percent": 80})


def test_the_usage_settings_belong_to_the_claude_runtime() -> None:
    """Set on another runtime they would be read by nothing, which looks like a
    limit and is not one."""
    with pytest.raises(ValidationError, match=r"runtimes\.acp\.limits"):
        WorkspaceConfig(
            runtimes={
                "acp": RuntimeConfig(
                    limits=ClaudeLimitsConfig(session=UsageWindowConfig(usage_pause_pct=80))
                )
            }
        )


def test_other_runtime_settings_are_unaffected() -> None:
    config = WorkspaceConfig(runtimes={"acp": RuntimeConfig(command=["agent", "acp"])})

    assert config.runtimes["acp"].command == ["agent", "acp"]


def test_the_sections_load_from_a_mapping() -> None:
    claude = (
        WorkspaceConfig.model_validate(
            {
                "runtimes": {
                    CLAUDE_CODE: {
                        "limits": {
                            "session": {"usage_pause_pct": 85, "usage_pause_ceiling_pct": 92},
                            "weekly": {"usage_pause_pct": 90, "usage_relief_fraction": 0.1},
                        }
                    }
                }
            }
        )
        .runtimes[CLAUDE_CODE]
        .limits
    )

    assert (claude.session.usage_pause_pct, claude.session.usage_ceiling_pct) == (85, 92)
    assert (claude.weekly.usage_pause_pct, claude.weekly.usage_ceiling_pct) == (90, 90)
    assert (claude.session.usage_relief_fraction, claude.weekly.usage_relief_fraction) == (
        0.25,
        0.1,
    )


# --- the old keys --------------------------------------------------------------


def test_the_old_limits_keys_are_read_into_both_windows() -> None:
    """One number served both windows then, so both get it now."""
    config = WorkspaceConfig.model_validate(
        {"limits": {"usage_pause_pct": 85, "usage_ceiling_pct": 92, "max_review_rounds": 2}}
    )

    claude = config.runtimes[CLAUDE_CODE].limits
    for window in (claude.session, claude.weekly):
        assert (window.usage_pause_pct, window.usage_ceiling_pct) == (85, 92)
    assert config.limits.max_review_rounds == 2, "the rest of limits is untouched"


def test_a_file_with_only_the_old_pause_percent_keeps_its_old_ramp() -> None:
    """The old ceiling defaulted to 90, so a ramp was on unless turned off.
    A file written then must behave as it did, not quietly stop ramping."""
    claude = (
        WorkspaceConfig.model_validate({"limits": {"usage_pause_pct": 60}})
        .runtimes[CLAUDE_CODE]
        .limits
    )

    assert claude.session.usage_pause_pct == 60
    assert claude.session.usage_ceiling_pct == claude.weekly.usage_ceiling_pct == 90


def test_the_old_relief_and_buffer_keys_move_too_to_both_windows() -> None:
    claude = (
        WorkspaceConfig.model_validate(
            {"limits": {"usage_relief_fraction": 0.5, "usage_resume_buffer_pct": 8}}
        )
        .runtimes[CLAUDE_CODE]
        .limits
    )

    for window in (claude.session, claude.weekly):
        assert (window.usage_relief_fraction, window.usage_resume_buffer_pct) == (0.5, 8)


def test_old_and_new_keys_together_are_refused() -> None:
    """Two places saying how full a window may get, with no rule for which
    wins, is how a limit gets raised by the one nobody looked at."""
    with pytest.raises(ValidationError, match="both set the usage"):
        WorkspaceConfig.model_validate(
            {
                "limits": {"usage_pause_pct": 80},
                "runtimes": {CLAUDE_CODE: {"limits": {"weekly": {"usage_pause_pct": 85}}}},
            }
        )


def test_the_old_keys_still_refuse_a_ceiling_below_the_pause_percent() -> None:
    with pytest.raises(ValidationError):
        WorkspaceConfig.model_validate({"limits": {"usage_pause_pct": 80, "usage_ceiling_pct": 70}})


def test_a_file_with_neither_gets_the_new_defaults() -> None:
    config_module.activate(WorkspaceConfig.model_validate({}), None)

    assert WorkspaceConfig.model_validate({}).runtimes.get(CLAUDE_CODE) is None
    assert Limits.configured().session == Band(pause_pct=70, ceiling_pct=70)
    assert Limits.configured().weekly == Band(pause_pct=70, ceiling_pct=70)
