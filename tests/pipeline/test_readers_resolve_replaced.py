"""Every reader of a unit's dependencies reads a replaced unit as its successor (spec:
a-replaced-unit-points-to-its-successor).

The scene: `d/1` stored a dependency on `x/3`, which a replan replaced by `x/5`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    SATISFIED,
    UnitState,
    base_of,
    blocked,
    branch_name,
    depth_of,
    effective_priority,
    emergency_start,
    followed_dependencies,
    open_parents,
    waiting_on,
    waiting_on_me,
)
from agent_build_kit.pipeline.wiring import build_upstream_incomplete
from tests.factories import stored_unit


def scene(successor: UnitState, **dependent: object) -> list[StoredUnit]:
    return [
        stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x", state=successor, branch="spec/x/5"),
        stored_unit(
            "d/1", change="d", depends_on=("x/3",), branch="spec/d/1", state=PLANNED, **dependent
        ),
    ]


def test_a_planned_successor_is_what_the_dependent_waits_on(tmp_path: Path) -> None:
    graph = scene(PLANNED)
    dependent = graph[-1]

    assert [u.id for u in waiting_on(dependent, graph)] == ["x/5"]
    assert blocked(dependent, graph)
    store = UnitStore(tmp_path / "units.json")
    store.import_units(graph)
    found = build_upstream_incomplete(store)(dependent)
    assert found is not None
    cause, message = found
    assert cause == Cause.UPSTREAM_WENT_BACK
    assert "x/5" in message
    assert "x/3" not in message


def test_a_successor_in_review_is_the_base_depth_and_open_parent_of_the_dependent() -> None:
    graph = scene(IN_REVIEW)
    dependent = graph[-1]

    assert base_of(dependent, graph) == branch_name(graph[1])
    assert depth_of(dependent, graph) == 2
    assert [u.id for u in open_parents(dependent, graph)] == ["x/5"]
    assert followed_dependencies(dependent, graph) == ["x/5"]
    assert waiting_on(dependent, graph) == []


def test_the_successor_gets_the_promotion_of_the_dependent() -> None:
    graph = scene(PLANNED, priority=1)
    successor = graph[1]

    assert [u.id for u in waiting_on_me(successor, graph)] == ["d/1"]
    assert effective_priority(successor, graph) == 1


def test_a_merged_successor_leaves_the_dependent_unheld() -> None:
    graph = scene(MERGED)
    dependent = graph[-1]

    assert followed_dependencies(dependent, graph) == ["x/5"]
    assert waiting_on(dependent, graph) == []
    assert not blocked(dependent, graph)


def test_a_cross_repo_dependent_of_a_satisfied_unit_follows_the_successor_of_its_parent() -> None:
    def graph(successor: UnitState) -> list[StoredUnit]:
        return [
            stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
            stored_unit("x/5", change="x", state=successor),
            stored_unit("s/1", change="s", state=SATISFIED, depends_on=("x/3",)),
            stored_unit("p/1", change="p", repo="platform", depends_on=("s/1",)),
        ]

    landed, open_ = graph(MERGED), graph(IN_REVIEW)

    assert waiting_on(landed[-1], landed) == []
    assert [u.id for u in waiting_on(open_[-1], open_)] == ["s/1"]


def test_a_merge_of_the_successor_moves_the_unit_that_stored_the_replaced_dependency() -> None:
    graph = scene(MERGED)
    graph[-1] = graph[-1].model_copy(update={"state": IN_REVIEW, "pr": 4})
    store = MagicMock()
    store.all.return_value = graph
    restacked: list[str] = []

    events.release_children(
        graph[1],
        store=store,
        restack=lambda **kw: restacked.append(kw["child"].id),
        retarget=lambda child, base: None,
    )

    assert restacked == ["d/1"]


def test_a_satisfied_successors_branch_is_kept_for_a_dependent_held_on_it(tmp_path: Path) -> None:
    graph = scene(SATISFIED)
    leaving = graph[1]
    graph[-1] = graph[-1].model_copy(
        update={"state": UnitState.HELD, "held_base": branch_name(leaving)}
    )
    store = UnitStore(tmp_path / "units.json")
    store.import_units(graph)
    deleted: list[str] = []
    logged: list[str] = []

    events.remove_satisfied(
        leaving,
        store=store,
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append(branch),
        on_new_base=lambda unit: True,
        log=logged.append,
    )

    assert deleted == []
    assert any("d/1 held for depth" in line for line in logged)


def waiting_scene(successor_history: list[dict[str, str]]) -> list[StoredUnit]:
    """`d/1` is in progress; its stored parent `x/3` went `unplanned` after `d/1` last changed."""
    return [
        stored_unit(
            "x/3",
            change="x",
            state=UnitState.UNPLANNED,
            superseded_by=("x/5",),
            history=(
                {"state": "in_review", "at": "2026-01-01T00:00:00"},
                {"state": "unplanned", "at": "2026-01-03T00:00:00"},
            ),
        ),
        stored_unit(
            "x/5", change="x", state=IN_REVIEW, branch="spec/x/5", history=tuple(successor_history)
        ),
        stored_unit(
            "d/1",
            change="d",
            depends_on=("x/3",),
            branch="spec/d/1",
            state=PLANNED,
            priority=0,
            history=({"state": "planned", "at": "2026-01-02T00:00:00"},),
        ),
    ]


def test_a_replaced_parents_unplanned_history_does_not_make_the_dependent_wait_for_room() -> None:
    graph = waiting_scene(
        [
            {"state": "in_review", "at": "2026-01-01T00:00:00"},
            {"state": "in_review", "at": "2026-01-04T00:00:00"},
        ]
    )

    assert not emergency_start(graph[-1], graph, excluded=())


def test_a_successor_outside_review_since_the_dependent_changed_makes_it_wait_for_room() -> None:
    graph = waiting_scene(
        [
            {"state": "in_review", "at": "2026-01-01T00:00:00"},
            {"state": "planned", "at": "2026-01-04T00:00:00"},
        ]
    )

    assert emergency_start(graph[-1], graph, excluded=())
