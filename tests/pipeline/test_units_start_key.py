"""The start key is the one order units start in, and it is public.

An open pull request sorts before a paused build, which sorts before new work; new work goes by
effective priority (a unit lent urgency by a unit that waits on it counts as that urgency), then
a handed-off unit, then the earlier effective age. The key given for waiting runs (no handed-off
units) is the key `ready_units` sorts a unit by.
"""

from agent_build_kit.pipeline.units import ready_units, start_key, start_rank
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked


def order(graph, handed_off=()) -> list[str]:
    ranked = sorted(graph, key=lambda unit: start_key(unit, graph, (), handed_off))
    return [unit.id for unit in ranked]


def test_the_rank_is_open_pull_request_then_paused_build_then_new() -> None:
    assert start_rank(new("review/1", state="in_review", pr=1)) == 0
    assert start_rank(worked("paused/1")) == 1
    assert start_rank(new("fresh/1")) == 2


def test_an_open_pull_request_sorts_before_a_paused_build_before_a_new_unit() -> None:
    graph = [
        new("fresh/1", priority=1),
        worked("paused/1", priority=4),
        new("review/1", state="in_review", pr=1, priority=4),
    ]

    assert order(graph) == ["review/1", "paused/1", "fresh/1"]
    assert start_key(graph[2], graph, (), ()) < start_key(graph[1], graph, (), ())
    assert start_key(graph[1], graph, (), ()) < start_key(graph[0], graph, (), ())


def test_among_new_units_the_more_urgent_priority_sorts_first() -> None:
    graph = [new("low/1", priority=4), new("high/1", priority=2)]

    assert order(graph) == ["high/1", "low/1"]


def test_a_unit_lent_urgency_by_a_unit_waiting_on_it_counts_as_that_urgency() -> None:
    graph = [
        new("plain/1", priority=2),
        new("prerequisite/1", priority=4),
        new("waiter/1", priority=1, depends_on=("prerequisite/1",)),
    ]

    assert start_key(graph[1], graph, (), ())[1] == 1
    assert order(graph).index("prerequisite/1") < order(graph).index("plain/1")


def test_a_handed_off_unit_sorts_before_another_of_equal_priority() -> None:
    graph = [new("other/1"), new("handed/1")]

    assert order(graph) == ["other/1", "handed/1"]
    assert order(graph, handed_off=("handed/1",)) == ["handed/1", "other/1"]


def test_a_handed_off_unit_does_not_go_ahead_of_a_more_urgent_one() -> None:
    graph = [new("handed/1", priority=3), new("urgent/1", priority=2)]

    assert order(graph, handed_off=("handed/1",)) == ["urgent/1", "handed/1"]


def test_of_equal_priority_and_hand_off_the_earlier_effective_age_sorts_first() -> None:
    graph = [new("older/1"), new("newer/1")]

    assert start_key(graph[0], graph, (), ()) < start_key(graph[1], graph, (), ())


def test_the_key_for_waiting_runs_equals_the_key_ready_units_sorts_by() -> None:
    graph = [
        new("late/1", priority=3),
        new("early/1", priority=2),
        worked("paused/1", priority=4),
        new("same-a/1", priority=2),
    ]
    ready = [unit.id for unit in ready_units(graph, max_concurrent=9, depth_cap=9)]

    assert ready == order(graph)
