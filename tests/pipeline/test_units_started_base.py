"""A started unit's base is chosen as an unstarted unit's is, whatever order its dependencies
are listed in.

Both pick the open parent the others are built on, else the deepest, a tie going to the later
in plan order. A started unit used to take the last one listed, so a `Needs:` that appended a
dependency further down the chain moved its base.
"""

from __future__ import annotations

from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, base_of
from tests.factories import replaced
from tests.factories import stored_unit as unit

STARTED = {"state": RUNNING, "branch": "spec/feature/9", "pr": 9}


def chain_graph(depends_on: tuple[str, ...]):
    """A (feature/1) in review, B (feature/2) built on A, and a unit that depends on both
    in the order given."""
    return [
        unit("feature/1", change="feature", state=IN_REVIEW, branch="spec/feature/1"),
        unit(
            "feature/2",
            change="feature",
            depends_on=("feature/1",),
            state=IN_REVIEW,
            branch="spec/feature/2",
        ),
        unit("feature/9", change="feature", depends_on=depends_on, **STARTED),
    ]


def test_a_needs_that_adds_the_grandparent_after_the_parent_keeps_the_parent_as_base() -> None:
    before = chain_graph(("feature/2",))
    after = chain_graph(("feature/2", "feature/1"))

    assert base_of(before[-1], before) == "spec/feature/2"
    assert base_of(after[-1], after) == "spec/feature/2"


def test_a_started_unit_has_the_same_base_for_both_orders_of_its_list() -> None:
    a_then_b = chain_graph(("feature/1", "feature/2"))
    b_then_a = chain_graph(("feature/2", "feature/1"))

    assert base_of(a_then_b[-1], a_then_b) == "spec/feature/2"
    assert base_of(b_then_a[-1], b_then_a) == "spec/feature/2"


def test_a_started_unit_has_the_base_an_unstarted_one_has_for_the_same_list() -> None:
    graph = chain_graph(("feature/2", "feature/1"))
    unstarted = replaced(graph, "feature/9", state=PLANNED, branch="", pr=None)
    started = graph[-1]

    assert base_of(unstarted[-1], unstarted) == "spec/feature/2"
    assert base_of(started, graph) == base_of(unstarted[-1], unstarted)


def unrelated_graph(depends_on: tuple[str, ...], *, deeper: bool):
    """Two parents no other parent builds on. `feature/2` is one layer deeper than `feature/1`
    when `deeper`, as it is built on a third open unit."""
    return [
        unit("feature/3", change="feature", state=IN_REVIEW, branch="spec/feature/3"),
        unit("feature/1", change="feature", state=IN_REVIEW, branch="spec/feature/1"),
        unit(
            "feature/2",
            change="feature",
            depends_on=("feature/3",) if deeper else (),
            state=IN_REVIEW,
            branch="spec/feature/2",
        ),
        unit("feature/9", change="feature", depends_on=depends_on, **STARTED),
    ]


def test_two_unrelated_open_parents_give_a_started_unit_the_deeper_one() -> None:
    for order in (("feature/2", "feature/1"), ("feature/1", "feature/2")):
        graph = unrelated_graph(order, deeper=True)
        assert base_of(graph[-1], graph) == "spec/feature/2", order


def test_a_tie_between_unrelated_open_parents_goes_to_the_later_in_plan_order() -> None:
    for order in (("feature/2", "feature/1"), ("feature/1", "feature/2")):
        graph = unrelated_graph(order, deeper=False)
        assert base_of(graph[-1], graph) == "spec/feature/2", order
