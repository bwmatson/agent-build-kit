"""A unit that has never started waits for all but one of its unrelated open parents.

Two open same-repo parents that neither builds on the other cannot both be a base:
the unit would start on one branch and lack the other's work. It waits for all but
one, and builds on the deepest (spec: a-unit-waits-for-all-but-one-open-parent).
The graphs are stored units, so a started unit has a recorded branch or a pull request.
"""

import pytest

from agent_build_kit.pipeline.units import (
    CLOSED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    base_of,
    blocked,
    branch_name,
    in_progress,
    open_parents,
    ready_units,
    second_parent_wait,
    uncounted,
    unrelated_open_parents,
    waiting_on,
)
from tests.factories import new_unit as new


def review(uid: str, pr: int = 1, **kw):
    return new(uid, state=IN_REVIEW, pr=pr, **kw)


def waits(graph, uid: str) -> list[str]:
    unit = next(u for u in graph if u.id == uid)
    return [parent.id for parent in waiting_on(unit, graph)]


def base(graph, uid: str) -> str:
    return base_of(next(u for u in graph if u.id == uid), graph)


def branch(graph, uid: str) -> str:
    return branch_name(next(u for u in graph if u.id == uid))


def unrelated(graph, uid: str) -> list[str]:
    unit = next(u for u in graph if u.id == uid)
    return [parent.id for parent in unrelated_open_parents(unit, graph)]


def ready(graph) -> list[str]:
    return [u.id for u in ready_units(graph, max_concurrent=9, depth_cap=9)]


# --- 1.1 two siblings in review -----------------------------------------------------


def test_a_unit_with_two_sibling_parents_in_review_is_not_ready() -> None:
    graph = [review("p1/1"), review("p2/1"), new("kid/1", depends_on=("p1/1", "p2/1"))]

    assert "kid/1" not in ready(graph)
    assert blocked(graph[2], graph)


def test_it_waits_for_the_earlier_of_two_siblings_of_equal_depth_and_builds_on_the_later() -> None:
    graph = [review("p1/1"), review("p2/1"), new("kid/1", depends_on=("p1/1", "p2/1"))]

    assert waits(graph, "kid/1") == ["p1/1"]
    assert base(graph, "kid/1") == branch(graph, "p2/1")


def test_the_order_of_depends_on_does_not_change_which_sibling_it_waits_for() -> None:
    graph = [review("p1/1"), review("p2/1"), new("kid/1", depends_on=("p2/1", "p1/1"))]

    assert waits(graph, "kid/1") == ["p1/1"]
    assert base(graph, "kid/1") == branch(graph, "p2/1")


def test_it_waits_for_the_shallower_sibling_and_builds_on_the_deeper() -> None:
    """`p2` is the later in plan order, but `p1` is built on an open root, so it is deeper."""
    graph = [
        review("root/1"),
        review("p1/1", depends_on=("root/1",)),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1")),
    ]

    assert waits(graph, "kid/1") == ["p2/1"]
    assert base(graph, "kid/1") == branch(graph, "p1/1")


def test_a_third_sibling_in_review_makes_it_wait_for_two() -> None:
    graph = [
        review("p1/1"),
        review("p2/1"),
        review("p3/1"),
        new("kid/1", depends_on=("p1/1", "p2/1", "p3/1")),
    ]

    assert waits(graph, "kid/1") == ["p1/1", "p2/1"]
    assert base(graph, "kid/1") == branch(graph, "p3/1")
    assert "kid/1" not in ready(graph)


def test_a_parent_in_review_and_one_still_planned_wait_as_a_dependency_does_today() -> None:
    graph = [review("p1/1"), new("p2/1"), new("kid/1", depends_on=("p1/1", "p2/1"))]

    assert unrelated(graph, "kid/1") == ["p1/1"]
    assert waits(graph, "kid/1") == ["p2/1"]


# --- 1.2 a sibling leaves ----------------------------------------------------------


@pytest.mark.parametrize("gone", [MERGED, SATISFIED])
def test_the_unit_is_ready_once_one_sibling_has_merged_or_been_satisfied_and_landed(
    gone: str,
) -> None:
    graph = [
        review("p1/1"),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1")),
    ]
    graph[0] = graph[0].model_copy(update={"state": gone})
    if gone == SATISFIED:
        graph.insert(0, new("trunk/1", state=MERGED))
        graph[1] = graph[1].model_copy(update={"depends_on": ("trunk/1",)})

    assert unrelated(graph, "kid/1") == ["p2/1"]
    assert waits(graph, "kid/1") == []
    assert "kid/1" in ready(graph)
    assert base(graph, "kid/1") == branch(graph, "p2/1")


def test_a_closed_sibling_ends_the_second_parent_wait_but_still_holds_the_unit() -> None:
    """A closed dependency holds its dependent as it did before this rule."""
    graph = [
        new("p1/1", state=CLOSED),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1")),
    ]

    assert unrelated(graph, "kid/1") == ["p2/1"]
    assert second_parent_wait(graph[2], graph) == ""
    assert waits(graph, "kid/1") == ["p1/1"]
    assert "kid/1" not in ready(graph)


def test_a_sibling_sent_back_for_rework_is_waited_for_as_any_dependency_with_no_extra_entry() -> (
    None
):
    graph = [
        new("p1/1", state=PLANNED, pr=4, feedback="use a Sequence"),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1")),
    ]

    assert unrelated(graph, "kid/1") == ["p2/1"]
    assert waits(graph, "kid/1") == ["p1/1"]
    assert "kid/1" not in ready(graph)


@pytest.mark.parametrize("state", [CLOSED, HELD, RUNNING])
def test_a_parent_that_is_not_in_review_is_not_an_open_parent(state: str) -> None:
    graph = [new("p1/1", state=state), review("p2/1"), new("kid/1", depends_on=("p1/1", "p2/1"))]

    assert [p.id for p in open_parents(graph[2], graph)] == ["p2/1"]


# --- 1.3 a chain ---------------------------------------------------------------------


@pytest.mark.parametrize("listed", [("a/1", "b/1"), ("b/1", "a/1")])
def test_a_chain_of_parents_is_ready_and_builds_on_the_descendant(listed: tuple[str, ...]) -> None:
    graph = [review("a/1"), review("b/1", depends_on=("a/1",)), new("kid/1", depends_on=listed)]

    assert waits(graph, "kid/1") == []
    assert "kid/1" in ready(graph)
    assert base(graph, "kid/1") == branch(graph, "b/1")
    assert [p.id for p in unrelated_open_parents(graph[2], graph)] == ["b/1"]


@pytest.mark.parametrize("listed", [("a/1", "c/1"), ("c/1", "a/1")])
def test_a_chain_through_a_unit_between_them_behaves_the_same(listed: tuple[str, ...]) -> None:
    graph = [
        review("a/1"),
        new("b/1", state=MERGED, depends_on=("a/1",)),
        review("c/1", depends_on=("b/1",)),
        new("kid/1", depends_on=listed),
    ]

    assert unrelated(graph, "kid/1") == ["c/1"]
    assert waits(graph, "kid/1") == []
    assert base(graph, "kid/1") == branch(graph, "c/1")


@pytest.mark.parametrize("listed", [("a/1", "c/1"), ("c/1", "a/1")])
def test_a_chain_through_a_satisfied_unit_behaves_the_same(listed: tuple[str, ...]) -> None:
    graph = [
        review("a/1"),
        new("b/1", state=SATISFIED, depends_on=("a/1",)),
        review("c/1", depends_on=("b/1",)),
        new("kid/1", depends_on=listed),
    ]

    assert unrelated(graph, "kid/1") == ["c/1"]
    assert waits(graph, "kid/1") == []
    assert base(graph, "kid/1") == branch(graph, "c/1")


# --- 1.4 a diamond -----------------------------------------------------------------


@pytest.mark.parametrize("root_state", [IN_REVIEW, MERGED])
def test_a_diamond_waits_as_for_two_siblings_and_never_names_the_root(root_state: str) -> None:
    graph = [
        new("root/1", state=root_state, pr=1),
        review("s1/1", depends_on=("root/1",)),
        review("s2/1", pr=3, depends_on=("root/1",)),
        new("kid/1", depends_on=("s1/1", "s2/1")),
    ]

    assert waits(graph, "kid/1") == ["s1/1"]
    assert base(graph, "kid/1") == branch(graph, "s2/1")
    assert "kid/1" not in ready(graph)


# --- 1.5 satisfied and cross-repo parents -------------------------------------------


def test_a_satisfied_parent_is_replaced_by_what_it_was_built_on() -> None:
    graph = [
        review("p/1"),
        review("q/1"),
        new("sat/1", state=SATISFIED, depends_on=("p/1",)),
        new("kid/1", depends_on=("sat/1", "q/1")),
    ]

    assert waits(graph, "kid/1") == ["p/1"]
    assert [p.id for p in open_parents(graph[3], graph)] == ["p/1", "q/1"]
    assert "kid/1" not in ready(graph)


def test_a_satisfied_parent_built_on_the_other_open_parent_leaves_one() -> None:
    graph = [
        review("q/1"),
        new("sat/1", state=SATISFIED, depends_on=("q/1",)),
        new("kid/1", depends_on=("sat/1", "q/1")),
    ]

    assert unrelated(graph, "kid/1") == ["q/1"]
    assert waits(graph, "kid/1") == []
    assert base(graph, "kid/1") == branch(graph, "q/1")
    assert "kid/1" in ready(graph)


def test_a_cross_repo_parent_in_review_waits_for_a_merge_and_is_not_an_open_parent() -> None:
    graph = [
        review("same/1"),
        review("other/1", repo="platform"),
        new("kid/1", depends_on=("same/1", "other/1")),
    ]

    assert waits(graph, "kid/1") == ["other/1"]
    assert [p.id for p in open_parents(graph[2], graph)] == ["same/1"]


def test_a_same_repo_open_parent_and_a_merged_cross_repo_one_leave_the_unit_ready() -> None:
    graph = [
        review("same/1"),
        new("other/1", repo="platform", state=MERGED),
        new("kid/1", depends_on=("same/1", "other/1")),
    ]

    assert unrelated(graph, "kid/1") == ["same/1"]
    assert waits(graph, "kid/1") == []
    assert base(graph, "kid/1") == branch(graph, "same/1")


# --- 1.6 a started unit ------------------------------------------------------------


@pytest.mark.parametrize(
    "started",
    [{"branch": "spec/kid/1"}, {"pr": 9}, {"branch": "spec/kid/1", "feedback": "rework it"}],
    ids=["a recorded branch", "a pull request", "planned again for rework"],
)
def test_a_started_unit_keeps_the_wait_the_base_and_the_count_it_had(started: dict) -> None:
    graph = [
        review("p1/1"),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1"), **started),
    ]
    kid = graph[2]

    assert unrelated(graph, "kid/1") == ["p1/1", "p2/1"]
    assert waits(graph, "kid/1") == []
    assert not blocked(kid, graph)
    assert in_progress(kid, graph)
    assert kid not in uncounted(graph)
    assert "kid/1" in ready(graph)


@pytest.mark.parametrize(
    ("listed", "deeper", "expected"),
    [
        (("p1/1", "p2/1"), False, "p2/1"),
        (("p2/1", "p1/1"), False, "p1/1"),
        (("p1/1", "p2/1"), True, "p2/1"),
    ],
    ids=["plan order", "reversed", "a deeper sibling listed first"],
)
def test_a_started_unit_keeps_the_base_it_has_today(
    listed: tuple[str, ...], deeper: bool, expected: str
) -> None:
    """The last open dependency in the order listed, as before the rule, whatever the depths."""
    graph = [review("p1/1"), review("p2/1")]
    if deeper:
        graph = [review("root/1"), review("p1/1", depends_on=("root/1",)), review("p2/1")]
    graph.append(new("kid/1", depends_on=listed, branch="spec/kid/1"))

    assert len(unrelated(graph, "kid/1")) == 2
    assert base(graph, "kid/1") == branch(graph, expected)


def test_a_second_parent_added_to_a_started_unit_changes_nothing_for_it() -> None:
    one = [review("p1/1"), review("p2/1"), new("kid/1", depends_on=("p1/1",), branch="spec/k")]
    two = [
        review("p1/1"),
        review("p2/1"),
        new("kid/1", depends_on=("p1/1", "p2/1"), branch="spec/k"),
    ]

    assert unrelated(two, "kid/1") == ["p1/1", "p2/1"]
    assert waits(two, "kid/1") == waits(one, "kid/1") == []
    assert not blocked(two[2], two)
    assert in_progress(two[2], two) == in_progress(one[2], one)


# --- 1.7 nothing is stored by waiting ------------------------------------------------


def test_the_wait_ends_with_no_stored_state_changed() -> None:
    graph = [review("p1/1"), review("p2/1"), new("kid/1", depends_on=("p1/1", "p2/1"))]
    before = graph[2]

    assert blocked(graph[2], graph)

    merged = [graph[0].model_copy(update={"state": MERGED}), *graph[1:]]

    assert not blocked(merged[2], merged)
    assert "kid/1" in ready(merged)
    assert merged[2] == before
