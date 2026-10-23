"""A window that reset since the reading is estimated from its reset: the climb plus the cost
recorded at or after the reset, with no intercept (spec: usage-pause)."""

from agent_build_kit.pipeline.usage_guard import decide_start
from tests.usage_cost_estimate import HOUR, MINUTE, cost_fit, keep_fits, paused, row
from tests.usage_host import Host


def reset_an_hour_ago(host: Host) -> None:
    """The session read three hours ago and reset an hour ago, with a climb of six points over
    that hour (3 for the floor, 3 for the margin); $4.00 recorded before the reset and $1.00
    after it, and the weekly at 40% as it was."""
    paused(
        host,
        age=3 * HOUR,
        session=88.0,
        weekly=40.0,
        session_resets_in=-1 * HOUR,
        usage_climb_floor=0.05,
        usage_climb_margin_pct=3,
    )
    row(host, "implement", 4.00, unit="feature/1", ago=2 * HOUR)
    row(host, "implement", 1.00, unit="feature/2", ago=30 * MINUTE)
    keep_fits(host, session=cost_fit(2, intercept=5, flat=10), weekly=cost_fit(0.4, flat=2))


def test_a_reset_session_takes_the_climb_and_the_cost_after_the_reset_only(host: Host) -> None:
    reset_an_hour_ago(host)

    reason = decide_start().reason

    assert "session ~8% estimated (0% read + 8% spent from $1.00 recorded)" in reason


def test_a_weekly_that_has_not_reset_keeps_its_reading_and_adds_its_cost(host: Host) -> None:
    reset_an_hour_ago(host)

    reason = decide_start().reason

    assert "weekly ~42% estimated (40% read + 2% spent from $5.00 recorded)" in reason
