"""Finding a cycle in a unit graph, and dropping the planner edges that would close one
(spec: unit-scheduling). Both are pure over their arguments: graphs are dicts and units."""

from __future__ import annotations

import itertools

import pytest

from agent_build_kit.pipeline.cycles import CycleEdge, drop_cycle_edges, find_cycle
from agent_build_kit.pipeline.units import MERGED
from tests.factories import new_unit, unit


@pytest.mark.parametrize(
    ("edges", "cycle"),
    [
        pytest.param({"A": ["B"], "B": ["A"]}, ("A", "B", "A"), id="two units"),
        pytest.param(
            {"a/1": ["b/1"], "b/1": ["c/1"], "c/1": ["a/1"]},
            ("a/1", "b/1", "c/1", "a/1"),
            id="three units across three changes",
        ),
        pytest.param({"A": ["A"]}, ("A", "A"), id="a self edge"),
        pytest.param(
            {"X": ["A"], "A": ["B"], "B": ["A"]}, ("A", "B", "A"), id="reached from outside it"
        ),
    ],
)
def test_a_cycle_is_named_closing_on_its_first_unit(
    edges: dict[str, list[str]], cycle: tuple[str, ...]
) -> None:
    assert find_cycle(edges) == cycle


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param({"C": ["B"], "B": ["A"], "A": []}, id="a chain"),
        pytest.param({"D": ["B", "C"], "B": ["A"], "C": ["A"], "A": []}, id="a diamond"),
        pytest.param({"B": ["A"], "C": ["A"], "A": []}, id="two units sharing a parent"),
        pytest.param({}, id="an empty graph"),
    ],
)
def test_no_cycle_is_found_in_a_chain_a_diamond_or_nothing(edges: dict[str, list[str]]) -> None:
    assert find_cycle(edges) == ()


def test_the_same_cycle_is_found_whatever_order_the_keys_come_in() -> None:
    edges = {"X": ["A"], "A": ["B"], "B": ["C"], "C": ["A"]}

    found = {find_cycle(dict(order)) for order in itertools.permutations(edges.items())}

    assert found == {("A", "B", "C", "A")}


def test_a_planner_edge_back_into_a_change_that_needs_it_is_dropped_naming_the_cycle() -> None:
    plan = [unit("add/1", change="add", depends_on=("hold/2",))]
    stored = [
        new_unit("hold/1"),
        new_unit("hold/2", depends_on=("hold/1",)),
    ]

    result = drop_cycle_edges(plan, stored, {"hold/1": ("add/1",)})

    assert [(u.id, u.depends_on) for u in result.units] == [("add/1", ())]
    assert result.dropped == (
        CycleEdge(
            unit="add/1",
            dependency="hold/2",
            cycle=("add/1", "hold/2", "hold/1", "add/1"),
        ),
    )
    assert result.cycle == ()


def test_a_planner_edge_closing_a_cycle_through_a_stored_planner_edge_is_dropped_and_it_stays() -> (
    None
):
    plan = [unit("add/1", change="add", depends_on=("other/1",))]
    stored = [new_unit("other/1", depends_on=("add/1",))]

    result = drop_cycle_edges(plan, stored, {})

    assert [(u.id, u.depends_on) for u in result.units] == [("add/1", ())]
    assert [(e.unit, e.dependency) for e in result.dropped] == [("add/1", "other/1")]
    assert stored[0].depends_on == ("add/1",)


def test_a_planner_edge_to_a_stored_unit_that_closes_no_cycle_is_kept() -> None:
    plan = [unit("add/1", change="add", depends_on=("other/1",))]
    stored = [new_unit("other/1"), new_unit("third/1", depends_on=("other/1",))]

    result = drop_cycle_edges(plan, stored, {})

    assert [(u.id, u.depends_on) for u in result.units] == [("add/1", ("other/1",))]
    assert result.dropped == ()


def test_edges_are_tried_in_the_plans_order_so_the_same_input_drops_the_same_edge() -> None:
    # Either planner edge closes a cycle with the other: whichever is tried first stays.
    plan = [
        unit("add/1", change="add", depends_on=("add/2",)),
        unit("add/2", change="add", depends_on=("add/1",)),
    ]

    first = drop_cycle_edges(plan, [], {})
    again = drop_cycle_edges(plan, [], {})

    assert first == again
    assert [(e.unit, e.dependency) for e in first.dropped] == [("add/2", "add/1")]
    assert [(u.id, u.depends_on) for u in first.units] == [("add/1", ("add/2",)), ("add/2", ())]


def test_a_cycle_among_declared_needs_alone_drops_nothing_and_is_returned() -> None:
    plan = [unit("alpha/1", change="alpha")]
    stored = [new_unit("beta/1")]

    result = drop_cycle_edges(plan, stored, {"alpha/1": ("beta/1",), "beta/1": ("alpha/1",)})

    assert result.units == tuple(plan)
    assert result.dropped == ()
    assert result.cycle == ("alpha/1", "beta/1", "alpha/1")


def test_a_cycle_over_three_changes_is_closed_only_by_the_planner_edge_which_is_dropped() -> None:
    # a/1 -> b/1 is a Needs: line, b/1 -> c/1 a stored planner edge, c/1 -> a/1 the plan's.
    plan = [unit("c/1", change="c", depends_on=("a/1",))]
    stored = [new_unit("a/1"), new_unit("b/1", depends_on=("c/1",))]

    result = drop_cycle_edges(plan, stored, {"a/1": ("b/1",)})

    assert [(e.unit, e.dependency) for e in result.dropped] == [("c/1", "a/1")]
    assert result.dropped[0].cycle == ("c/1", "a/1", "b/1", "c/1")
    assert result.units[0].depends_on == ()


def test_a_finished_unit_closes_no_cycle() -> None:
    plan = [unit("add/1", change="add", depends_on=("done/1",))]
    stored = [new_unit("done/1", depends_on=("add/1",), state=MERGED)]

    result = drop_cycle_edges(plan, stored, {})

    assert result.units[0].depends_on == ("done/1",)
    assert result.dropped == ()
