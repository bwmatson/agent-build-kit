"""Which units wait on a unit, and how urgent that makes it.

`waiting_on_me` follows the reverse of `depends_on` across repos and through
chains, and is the one definition of who waits on a unit; a unit's effective
priority is the smallest priority among itself and those units.
"""

from collections.abc import Iterable

from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    IN_REVIEW,
    MERGED,
    RUNNING,
    SATISFIED,
    Unit,
    effective_priority,
    waiting_on_me,
)
from tests.factories import unit


def ids(units: Iterable[Unit]) -> set[str]:
    return {u.id for u in units}


def test_a_direct_dependent_waits() -> None:
    prerequisite = unit("a/1")
    graph = [prerequisite, unit("b/1", depends_on=("a/1",)), unit("c/1")]

    assert ids(waiting_on_me(prerequisite, graph)) == {"b/1"}


def test_a_chain_waits() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",)),
        unit("c/1", depends_on=("b/1",)),
        unit("d/1", depends_on=("c/1",)),
    ]

    assert ids(waiting_on_me(prerequisite, graph)) == {"b/1", "c/1", "d/1"}


def test_a_dependent_in_another_repo_waits() -> None:
    prerequisite = unit("a/1", repo="platform")
    graph = [prerequisite, unit("b/1", repo="app", depends_on=("a/1",))]

    assert ids(waiting_on_me(prerequisite, graph)) == {"b/1"}


def test_a_dependent_through_another_repo_waits() -> None:
    prerequisite = unit("a/1", repo="platform")
    graph = [
        prerequisite,
        unit("b/1", repo="app", depends_on=("a/1",)),
        unit("c/1", repo="platform", depends_on=("b/1",)),
    ]

    assert ids(waiting_on_me(prerequisite, graph)) == {"b/1", "c/1"}


def test_a_gated_dependent_waits() -> None:
    prerequisite = unit("a/1")
    graph = [prerequisite, unit("b/1", depends_on=("a/1",), merge_before=("a/1",))]

    assert ids(waiting_on_me(prerequisite, graph)) == {"b/1"}


def test_merged_closed_and_satisfied_dependents_do_not_wait() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("m/1", depends_on=("a/1",), state=MERGED),
        unit("c/1", depends_on=("a/1",), state=CLOSED),
        unit("s/1", depends_on=("a/1",), state=SATISFIED),
    ]

    assert waiting_on_me(prerequisite, graph) == []


def test_units_in_any_other_state_wait() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("r/1", depends_on=("a/1",), state=RUNNING),
        unit("v/1", depends_on=("a/1",), state=IN_REVIEW),
        unit("f/1", depends_on=("a/1",), state=FAILED),
    ]

    assert ids(waiting_on_me(prerequisite, graph)) == {"r/1", "v/1", "f/1"}


def test_the_chain_is_looked_through_a_satisfied_unit() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("s/1", depends_on=("a/1",), state=SATISFIED),
        unit("w/1", depends_on=("s/1",)),
    ]

    assert ids(waiting_on_me(prerequisite, graph)) == {"w/1"}


def test_the_chain_is_looked_through_a_satisfied_unit_in_another_repo() -> None:
    prerequisite = unit("a/1", repo="platform")
    graph = [
        prerequisite,
        unit("s/1", repo="app", depends_on=("a/1",), state=SATISFIED),
        unit("w/1", repo="app", depends_on=("s/1",)),
    ]

    assert ids(waiting_on_me(prerequisite, graph)) == {"w/1"}


def test_a_dependent_of_two_units_waits_on_each() -> None:
    first, second = unit("a/1"), unit("a/2")
    graph = [first, second, unit("w/1", depends_on=("a/1", "a/2"))]

    assert [u.id for u in waiting_on_me(first, graph)] == ["w/1"]
    assert [u.id for u in waiting_on_me(second, graph)] == ["w/1"]


def test_a_dependent_reached_two_ways_is_listed_once() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",)),
        unit("c/1", depends_on=("a/1",)),
        unit("d/1", depends_on=("b/1", "c/1")),
    ]

    found = [u.id for u in waiting_on_me(prerequisite, graph)]

    assert sorted(found) == ["b/1", "c/1", "d/1"]


def test_a_cycle_does_not_loop() -> None:
    first = unit("a/1", depends_on=("c/1",))
    graph = [first, unit("b/1", depends_on=("a/1",)), unit("c/1", depends_on=("b/1",))]

    found = ids(waiting_on_me(first, graph))

    assert {"b/1", "c/1"} <= found
    assert "a/1" not in found


def test_a_unit_does_not_wait_on_itself() -> None:
    lone = unit("a/1", depends_on=("a/1",))

    assert waiting_on_me(lone, [lone]) == []


def test_the_excluded_units_are_left_out() -> None:
    prerequisite = unit("a/1")
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",)),
        unit("c/1", depends_on=("a/1",)),
    ]

    assert ids(waiting_on_me(prerequisite, graph, frozenset(["b/1"]))) == {"c/1"}


def test_nothing_waits_on_a_unit_nothing_depends_on() -> None:
    lone = unit("a/1")

    assert waiting_on_me(lone, [lone, unit("b/1", depends_on=("c/1",)), unit("c/1")]) == []


# --- effective priority --------------------------------------------------------


def test_a_prerequisite_takes_the_priority_of_a_unit_waiting_on_it() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [prerequisite, unit("b/1", depends_on=("a/1",), priority=1)]

    assert effective_priority(prerequisite, graph) == 1


def test_a_prerequisite_takes_the_priority_of_a_unit_further_down_the_chain() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",), priority=3),
        unit("c/1", depends_on=("b/1",), priority=1),
    ]

    assert effective_priority(prerequisite, graph) == 1


def test_a_prerequisite_takes_the_priority_of_a_waiter_in_another_repo() -> None:
    prerequisite = unit("a/1", repo="platform", priority=3)
    graph = [prerequisite, unit("b/1", repo="app", depends_on=("a/1",), priority=2)]

    assert effective_priority(prerequisite, graph) == 2


def test_the_most_urgent_of_several_waiters_counts() -> None:
    prerequisite = unit("a/1", priority=4)
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",), priority=3),
        unit("c/1", depends_on=("a/1",), priority=2),
        unit("d/1", depends_on=("a/1",), priority=5),
    ]

    assert effective_priority(prerequisite, graph) == 2


def test_a_prerequisite_of_only_nice_to_have_units_is_not_made_more_urgent() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [
        prerequisite,
        unit("b/1", depends_on=("a/1",), priority=5),
        unit("c/1", depends_on=("b/1",), priority=5),
    ]

    assert effective_priority(prerequisite, graph) == 3


def test_a_unit_is_never_less_urgent_than_its_own_priority() -> None:
    prerequisite = unit("a/1", priority=1)
    graph = [prerequisite, unit("b/1", depends_on=("a/1",), priority=5)]

    assert effective_priority(prerequisite, graph) == 1


def test_a_unit_nothing_waits_on_has_its_own_priority() -> None:
    lone = unit("a/1", priority=4)

    assert effective_priority(lone, [lone]) == 4


def test_a_satisfied_unit_in_the_chain_passes_the_priority_on() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [
        prerequisite,
        unit("s/1", depends_on=("a/1",), state=SATISFIED, priority=3),
        unit("w/1", depends_on=("s/1",), priority=1),
    ]

    assert effective_priority(prerequisite, graph) == 1


def test_merged_closed_and_satisfied_waiters_give_no_priority() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [
        prerequisite,
        unit("m/1", depends_on=("a/1",), state=MERGED, priority=1),
        unit("c/1", depends_on=("a/1",), state=CLOSED, priority=1),
        unit("s/1", depends_on=("a/1",), state=SATISFIED, priority=1),
    ]

    assert effective_priority(prerequisite, graph) == 3


def test_a_unit_left_out_of_the_round_gives_no_priority() -> None:
    prerequisite = unit("a/1", priority=3)
    graph = [prerequisite, unit("b/1", depends_on=("a/1",), priority=1)]

    assert effective_priority(prerequisite, graph, frozenset(["b/1"])) == 3


def test_a_cycle_does_not_loop_when_working_out_the_priority() -> None:
    first = unit("a/1", depends_on=("b/1",), priority=3)
    graph = [first, unit("b/1", depends_on=("a/1",), priority=2)]

    assert effective_priority(first, graph) == 2
