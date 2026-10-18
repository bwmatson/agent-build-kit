"""`direct_dependencies` is the transitive reduction of a unit's stored dependencies.

A dependency another of the unit's dependencies reaches through stored edges is left
out, however many units of any state or repository lie between; the rest keep the order
they were given in, and a stored cycle ends the walk and keeps its dependencies.
"""

from __future__ import annotations

from agent_build_kit.pipeline.units import MERGED, direct_dependencies
from tests.factories import stored_unit as unit


def reduced(graph, uid: str) -> tuple[str, ...]:
    return direct_dependencies(next(u for u in graph if u.id == uid), graph)


def test_a_chain_with_a_redundant_ancestor_reduces_to_the_parent() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("feature/1",)),
        unit("feature/3", depends_on=("feature/2", "feature/1")),
    ]

    assert reduced(graph, "feature/3") == ("feature/2",)


def test_a_redundant_ancestor_listed_first_is_still_dropped() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("feature/1",)),
        unit("feature/3", depends_on=("feature/1", "feature/2")),
    ]

    assert reduced(graph, "feature/3") == ("feature/2",)


def test_a_diamond_keeps_both_parents_and_not_the_root() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("feature/1",)),
        unit("feature/3", depends_on=("feature/1",)),
        unit("feature/4", depends_on=("feature/2", "feature/3", "feature/1")),
    ]

    assert reduced(graph, "feature/4") == ("feature/2", "feature/3")


def test_unrelated_dependencies_are_all_kept_in_the_order_given() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2"),
        unit("feature/3"),
        unit("feature/4", depends_on=("feature/3", "feature/1", "feature/2")),
    ]

    assert reduced(graph, "feature/4") == ("feature/3", "feature/1", "feature/2")


def test_a_path_through_a_merged_unit_in_another_repository_reduces() -> None:
    graph = [
        unit("feature/1", repo="app"),
        unit("feature/2", repo="platform", depends_on=("feature/1",), state=MERGED),
        unit("feature/3", repo="app", depends_on=("feature/1", "feature/2")),
    ]

    assert reduced(graph, "feature/3") == ("feature/2",)


def test_a_path_of_several_merged_units_reduces() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("feature/1",), state=MERGED),
        unit("feature/3", depends_on=("feature/2",), state=MERGED),
        unit("feature/4", depends_on=("feature/3", "feature/1")),
    ]

    assert reduced(graph, "feature/4") == ("feature/3",)


def test_a_dependency_naming_an_unknown_unit_is_kept() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("gone/1", "feature/1")),
    ]

    assert reduced(graph, "feature/2") == ("gone/1", "feature/1")


def test_a_stored_cycle_returns_and_keeps_the_dependencies_of_the_cycle() -> None:
    graph = [
        unit("feature/1", depends_on=("feature/2",)),
        unit("feature/2", depends_on=("feature/1",)),
        unit("feature/3", depends_on=("feature/1", "feature/2")),
    ]

    assert reduced(graph, "feature/1") == ("feature/2",)
    assert reduced(graph, "feature/2") == ("feature/1",)
    assert reduced(graph, "feature/3") == ("feature/1", "feature/2")


def test_a_unit_with_no_redundancy_gets_its_list_unchanged() -> None:
    graph = [
        unit("feature/1"),
        unit("feature/2", depends_on=("feature/1",)),
        unit("feature/3", depends_on=("feature/2",)),
    ]

    assert reduced(graph, "feature/3") == ("feature/2",)
    assert reduced(graph, "feature/1") == ()
