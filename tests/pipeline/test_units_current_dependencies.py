"""A dependency on a replaced unit is read as the units that carry its work
(spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    MERGED,
    PLANNED,
    REPLACED_DEPTH,
    UnitState,
    current_dependencies,
    resolve_replaced,
)
from tests.factories import stored_unit


def replaced(uid: str, *by: str, state: UnitState = UnitState.UNPLANNED) -> StoredUnit:
    return stored_unit(uid, state=state, superseded_by=by)


def test_a_live_unit_an_absent_id_and_a_replaced_unit_without_successors_stand_for_themselves() -> (
    None
):
    graph = [stored_unit("x/1", state=PLANNED), replaced("x/2")]

    assert resolve_replaced("x/1", graph) == ("x/1",)
    assert resolve_replaced("x/9", graph) == ("x/9",)
    assert resolve_replaced("x/2", graph) == ("x/2",)


def test_a_replaced_unit_stands_for_its_successor() -> None:
    graph = [replaced("x/3", "x/5"), stored_unit("x/5")]

    assert resolve_replaced("x/3", graph) == ("x/5",)


def test_a_chain_resolves_to_its_last_unit() -> None:
    graph = [replaced("a", "b"), replaced("b", "c"), stored_unit("c")]

    assert resolve_replaced("a", graph) == ("c",)


def test_a_split_resolves_to_both_successors_once_each_in_order() -> None:
    graph = [
        replaced("a", "b", "c"),
        stored_unit("b"),
        stored_unit("c"),
        replaced("d", "e", "f"),
        replaced("e", "f"),
        stored_unit("f"),
    ]

    assert resolve_replaced("a", graph) == ("b", "c")
    assert resolve_replaced("d", graph) == ("f",)


def test_two_units_naming_each_other_stand_for_the_id_asked() -> None:
    graph = [replaced("a", "b"), replaced("b", "a")]

    assert resolve_replaced("a", graph) == ("a",)
    assert resolve_replaced("b", graph) == ("b",)


def test_a_read_stops_after_following_the_bound_of_links() -> None:
    ids = [f"u/{n}" for n in range(1, 11)]
    graph = [replaced(uid, after) for uid, after in zip(ids, ids[1:], strict=False)]
    graph.append(replaced(ids[-1]))

    assert resolve_replaced(ids[0], graph) == (ids[REPLACED_DEPTH],)


def test_a_merged_successor_is_passed_on_unchanged() -> None:
    graph = [replaced("x/3", "x/5"), stored_unit("x/5", state=MERGED)]

    assert resolve_replaced("x/3", graph) == ("x/5",)


def test_current_dependencies_resolve_each_entry_keeping_order_without_repeats() -> None:
    graph = [
        stored_unit("x/1"),
        replaced("x/3", "x/5"),
        stored_unit("x/5"),
        stored_unit("x/6", depends_on=("x/3", "x/1", "x/5", "x/3")),
    ]

    assert current_dependencies(graph[-1], graph) == ("x/5", "x/1")


def test_current_dependencies_never_contain_the_unit_itself() -> None:
    graph = [replaced("x/3", "x/5"), stored_unit("x/5", depends_on=("x/3",))]

    assert current_dependencies(graph[-1], graph) == ()


def test_current_dependencies_leave_a_cross_repo_entry_as_it_is() -> None:
    graph = [
        stored_unit("platform/1", repo="platform"),
        stored_unit("x/6", depends_on=("platform/1", "platform/9")),
    ]

    assert current_dependencies(graph[-1], graph) == ("platform/1", "platform/9")
