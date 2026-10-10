"""The gates and the resume time decide through the one rule that asks the endpoint only
when a fresh reading could change the decision, so an endpoint that is down does not wedge
a start the held reading allows (spec: usage-pause).

Only the endpoint and the home directory are faked (`tests/usage_host.py`).
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.wiring import build_may_start, build_resume_at, build_usage_gate
from agent_build_kit.tracks import runner
from tests.usage_host import Host, called, configure, pause_at, payload


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    configure(**pause_at(92))


def held_twenty_percent(host: Host) -> None:
    """Taken two hours ago, three hours from the reset; every call now fails."""
    host.keep_reading(
        timedelta(hours=2), payload(session=20.0, session_resets_in=timedelta(hours=3))
    )


def held_ninety_percent_just_after_a_call(host: Host) -> None:
    host.keep_reading(
        timedelta(minutes=40), payload(session=90.0, session_resets_in=timedelta(hours=3))
    )
    called(host, timedelta(minutes=2), "timeout")


def test_a_gate_allows_a_start_the_held_reading_settles_while_the_endpoint_is_down(
    host: Host,
) -> None:
    held_twenty_percent(host)
    may_start, _ = build_usage_gate()

    allowed, _ = may_start()

    assert allowed
    assert host.asked == 0


def test_a_gate_refuses_inside_the_interval_with_that_reason_and_makes_no_call(
    host: Host,
) -> None:
    held_ninety_percent_just_after_a_call(host)
    may_start, resume_at = build_usage_gate()

    allowed, why = may_start()
    until = resume_at()

    assert not allowed
    assert "asked too recently" in why
    assert until is not None
    assert timedelta(minutes=12) < until - datetime.now(UTC) <= timedelta(minutes=13, seconds=5)
    assert host.asked == 0


def test_the_start_check_and_the_resume_time_make_no_call_when_the_held_reading_settles_it(
    host: Host,
) -> None:
    held_twenty_percent(host)

    allowed, _ = build_may_start()()
    until = build_resume_at()()

    assert allowed
    assert until is not None
    assert host.asked == 0


def test_the_tracks_start_check_is_the_same_decision(host: Host) -> None:
    held_twenty_percent(host)

    assert runner.has_headroom()
    assert host.asked == 0
