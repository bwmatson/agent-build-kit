"""A unit admitted on an estimate is kept with the step it was admitted for, under a key beside
the list of units, which stays what it was; the cap still counts units (spec: usage-pause)."""

import json

from agent_build_kit.pipeline.usage_guard import decide_start
from tests.usage_cost_estimate import paused
from tests.usage_host import Host


def kept(host: Host) -> dict:
    return json.loads(host.cache.read_text())


def test_the_step_is_kept_beside_the_list_of_units(host: Host) -> None:
    paused(host, session=10.0)

    decision = decide_start(unit="feature/1", step="review")

    assert decision.may_start
    assert kept(host)["estimate_units"] == ["feature/1"]
    assert kept(host)["estimate_steps"] == {"feature/1": "review"}


def test_a_second_admission_of_the_unit_is_not_counted_twice(host: Host) -> None:
    paused(host, session=10.0)

    decide_start(unit="feature/1", step="review")
    decide_start(unit="feature/1", step="review")

    assert kept(host)["estimate_units"] == ["feature/1"]
    assert kept(host)["estimate_steps"] == {"feature/1": "review"}


def test_a_start_with_no_step_keeps_no_step(host: Host) -> None:
    paused(host, session=10.0)

    decide_start(unit="feature/1")

    assert kept(host)["estimate_units"] == ["feature/1"]
    assert "estimate_steps" not in kept(host)


def test_the_cap_still_counts_units_and_not_steps(host: Host) -> None:
    paused(host, session=10.0, usage_estimate_max_starts=2)

    first = decide_start(unit="feature/1", step="review")
    again = decide_start(unit="feature/1", step="rework")
    second = decide_start(unit="feature/2", step="review")
    third = decide_start(unit="feature/3", step="review")

    assert [first.may_start, again.may_start, second.may_start, third.may_start] == [
        True,
        True,
        True,
        False,
    ]
    assert kept(host)["estimate_units"] == ["feature/1", "feature/2"]
