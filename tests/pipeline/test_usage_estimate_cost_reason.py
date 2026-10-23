"""The reason of an allowance or a refusal on a cost window says how much cost was counted and
how many units were not yet recorded; a units window keeps its wording, and `abk status`'s held
estimate line is the same text with no call (spec: usage-pause)."""

from datetime import timedelta

from agent_build_kit.pipeline.usage_guard import decide_start, held_estimate_line
from tests.usage_cost_estimate import admit, cost_fit, keep_fits, paused, row
from tests.usage_host import Host


def observed(host: Host, *, session: float = 61.0) -> None:
    paused(host, session=session, age=timedelta(minutes=89, seconds=30))
    keep_fits(host, session=cost_fit(2.65, intercept=5, flat=17))
    row(host, "review", 0.97, unit="feature/1")
    row(host, "rework", 0.48, unit="feature/2")


def test_the_reason_of_an_allowance_says_how_much_cost_was_counted(host: Host) -> None:
    paused(host, age=timedelta(minutes=54, seconds=30))
    keep_fits(host, session=cost_fit(2.65, intercept=5, flat=17))
    row(host, "review", 0.97, unit="feature/1")
    row(host, "rework", 0.48, unit="feature/2")

    decision = decide_start()

    assert decision.may_start
    assert "session ~69% estimated (61% read + 8% spent from $1.45 recorded) under 80%" in (
        decision.reason
    )
    assert "weekly ~10% estimated (6% read + 4% spent) under 80%" in decision.reason


def test_the_reason_of_a_refusal_rests_on_the_same_terms(host: Host) -> None:
    paused(host, session=70.0, age=timedelta(minutes=54, seconds=30))
    keep_fits(host, session=cost_fit(2.65, intercept=5, flat=17))
    row(host, "review", 2.00, unit="feature/1")

    decision = decide_start()

    assert not decision.may_start
    assert (
        "session ~80% estimated (70% read + 10% spent from $2.00 recorded) is not 5 points "
        "under 80%"
    ) in decision.reason


def test_a_unit_counted_at_the_flat_allowance_is_said_to_be_not_yet_recorded(host: Host) -> None:
    paused(host, session=50.0, age=timedelta(minutes=5, seconds=30))
    keep_fits(host, session=cost_fit(2.65, flat=10))
    row(host, "review", 1.00, unit="feature/1")
    admit(host, "feature/2")

    assert (
        "session ~63% estimated (50% read + 13% spent from $1.00 recorded, 1 unit not yet recorded)"
        in (decide_start().reason)
    )


def test_two_units_not_yet_recorded_are_counted_in_the_plural(host: Host) -> None:
    paused(host, session=30.0, age=timedelta(minutes=5, seconds=30))
    keep_fits(host, session=cost_fit(2.65, flat=10))
    admit(host, "feature/1", "feature/2")

    assert "2 units not yet recorded" in decide_start().reason


def test_the_status_line_is_the_same_text_with_no_call(host: Host) -> None:
    observed(host)

    decision = decide_start()
    line = held_estimate_line()

    assert host.asked == 0
    assert line == decision.reason
    assert line is not None and "from $1.45 recorded" in line
