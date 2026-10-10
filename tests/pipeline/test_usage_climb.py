"""How much usage could have been added since a reading comes from the fastest climb seen.

The climb is derived per window from the percentages the answered calls in the
record read, in points a minute; a configured floor stands when the record shows
less or nothing, and a margin is added (spec: usage-pause).
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline.usage_calls import UsageCall, most_added
from agent_build_kit.pipeline.usage_guard import decide_start
from tests.usage_host import Host, payload

START = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


def answered(minutes: float, session: int, weekly: int) -> UsageCall:
    return UsageCall(
        at=START + timedelta(minutes=minutes),
        caller="guard",
        outcome="ok",
        status=200,
        session_pct=session,
        weekly_pct=weekly,
    )


# A run in which the session climbed three points a minute at best and the week a tenth.
RUN = [
    answered(0, 10, 50),
    answered(10, 40, 51),  # session 3.0 a minute, week 0.1
    answered(20, 45, 51),  # session 0.5 a minute, week 0
]


def test_the_fastest_climb_times_the_minutes_since_the_reading_plus_the_margin() -> None:
    added = most_added(RUN, "session", minutes=10, floor=0.0, margin=2)

    assert added == pytest.approx(32.0)


def test_with_no_record_the_floor_is_used() -> None:
    added = most_added([], "session", minutes=10, floor=0.5, margin=2)

    assert added == pytest.approx(7.0)


def test_the_floor_is_a_lower_bound_when_the_record_shows_less() -> None:
    added = most_added(RUN, "weekly", minutes=10, floor=0.5, margin=1)

    assert added == pytest.approx(6.0)


def test_a_record_that_shows_more_than_the_floor_is_not_lowered_to_it() -> None:
    added = most_added(RUN, "session", minutes=10, floor=0.5, margin=0)

    assert added == pytest.approx(30.0)


# --- 2.2 each window has its own rate ---------------------------------------------------


def test_the_session_and_week_windows_use_their_own_rates() -> None:
    session = most_added(RUN, "session", minutes=10, floor=0.0, margin=0)
    weekly = most_added(RUN, "weekly", minutes=10, floor=0.0, margin=0)

    assert session == pytest.approx(30.0)
    assert weekly == pytest.approx(1.0)


def test_a_fall_when_a_window_resets_is_not_a_climb_and_a_failed_call_is_not_a_reading() -> None:
    run = [
        answered(0, 60, 50),
        answered(5, 4, 50),  # the session window reset
        answered(10, 6, 50),  # 0.4 a minute
        UsageCall(at=START + timedelta(minutes=11), caller="guard", outcome="timeout"),
        UsageCall(at=START + timedelta(minutes=12), caller="guard", outcome="cache", age_seconds=9),
    ]

    added = most_added(run, "session", minutes=10, floor=0.0, margin=0)

    assert added == pytest.approx(4.0)


# --- 2.3 the settings are used in the rule ----------------------------------------------


def configure(**limits: object) -> None:
    config_module.activate(
        WorkspaceConfig.model_validate({"runtimes": {"claude_code": {"limits": limits}}}), None
    )


def record_session_climb(host: Host, *, per_minute: float) -> None:
    """Two answered calls, an hour ago, between which the session climbed `per_minute`."""
    first = datetime.now(UTC) - timedelta(minutes=70)
    host.seed(
        *[
            {
                "at": (first + timedelta(minutes=10 * step)).isoformat(),
                "caller": "guard",
                "outcome": "ok",
                "status": 200,
                "latency_ms": 100,
                "headers": {},
                "session_pct": 10 + int(per_minute * 10 * step),
                "weekly_pct": 5,
            }
            for step in range(2)
        ]
    )


def twenty_minute_old_reading(host: Host) -> None:
    host.keep_reading(
        timedelta(minutes=20), payload(session=60.0, session_resets_in=timedelta(hours=3))
    )


def test_a_climb_in_the_record_makes_a_reading_with_that_much_headroom_ask_the_endpoint(
    host: Host,
) -> None:
    """Sixty and the floor's four points is far under ninety-two, but the record's three a
    minute makes it sixty more."""
    configure(
        session={"usage_pause_pct": 92},
        weekly={"usage_pause_pct": 92},
        usage_climb_floor=0.2,
        usage_climb_margin_pct=0,
    )
    record_session_climb(host, per_minute=3.0)
    twenty_minute_old_reading(host)
    host.answers = [payload(session=61.0)]

    decide_start()

    assert host.asked == 1


def test_with_no_record_the_configured_floor_decides(host: Host) -> None:
    """Sixty, and twenty minutes at two points a minute reaches ninety-two; at a fifth, not."""
    twenty_minute_old_reading(host)
    configure(
        session={"usage_pause_pct": 92},
        weekly={"usage_pause_pct": 92},
        usage_climb_floor=0.2,
        usage_climb_margin_pct=0,
    )
    assert decide_start().may_start
    assert host.asked == 0

    configure(
        session={"usage_pause_pct": 92},
        weekly={"usage_pause_pct": 92},
        usage_climb_floor=2.0,
        usage_climb_margin_pct=0,
    )
    host.answers = [payload(session=61.0)]
    decide_start()
    assert host.asked == 1
