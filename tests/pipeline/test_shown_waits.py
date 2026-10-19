"""What a unit waits on is asked of the unit as the views show it, so a wait names only
dependencies the views draw and list."""

from __future__ import annotations

from agent_build_kit.pipeline.units import shown_dependencies, shown_waits
from tests.factories import stored_unit as unit


def test_a_wait_through_an_unreduced_satisfied_unit_still_names_the_failed_ancestor() -> None:
    graph = [
        unit("a/1", change="a", state="failed"),
        unit("a/2", change="a", state="satisfied", depends_on=("a/1",)),
        unit("a/3", change="a", depends_on=("a/1", "a/2")),
    ]

    assert [parent.id for parent in shown_waits(graph[2], graph)] == ["a/1"]


def test_a_wait_names_what_the_views_show_when_a_dependency_was_replaced() -> None:
    graph = [
        unit("x/1", change="x", state="unplanned", superseded_by=("y/1",)),
        unit("y/1", change="y"),
        unit("b/1", change="b", depends_on=("y/1",)),
        unit("c/1", change="c", depends_on=("x/1", "b/1")),
    ]

    shown = shown_dependencies(graph[3], graph)

    assert shown == ("b/1",)
    assert [parent.id for parent in shown_waits(graph[3], graph)] == list(shown)
