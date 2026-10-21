"""Pinning tests: a started unit parked before its first agent step counts as in progress for its
account, and `max_concurrent_stacks` counts such units by project (spec: capacity-checks, a
parked started unit holds its slot)."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import RUNNING, Unit, in_progress, ready_units, start_room
from tests.factories import new_unit

LIMIT = 2


def account_of(unit: Unit) -> str:
    """Stands in for the account of a repo: `app` and `platform` are two accounts."""
    return unit.repo


def parked(uid: str, repo: str = "app") -> StoredUnit:
    return new_unit(uid, repo=repo, state=RUNNING, branch=f"spec/{uid}")


def admitted(graph: list[StoredUnit]) -> list[str]:
    started = ready_units(
        graph,
        max_concurrent=9,
        depth_cap=9,
        max_units_in_progress=LIMIT,
        slot_of=account_of,
        slot_limit=lambda _: LIMIT,
    )
    return [unit.id for unit in started]


def test_a_unit_that_ran_prepare_and_is_parked_counts_as_in_progress() -> None:
    unit = parked("one/1")

    assert in_progress(unit, [unit])


def test_two_parked_units_leave_no_room_under_a_limit_of_two_for_their_account() -> None:
    graph = [parked("one/1"), parked("two/1"), new_unit("three/1")]

    assert start_room(graph, LIMIT, "app", account_of) == 0


def test_a_third_ready_unit_of_the_same_account_is_not_admitted() -> None:
    graph = [parked("one/1"), parked("two/1"), new_unit("three/1")]

    assert admitted(graph) == []


def test_a_ready_unit_of_another_account_is_admitted() -> None:
    graph = [parked("one/1"), parked("two/1"), new_unit("three/1", repo="platform")]

    assert admitted(graph) == ["three/1"]


def test_a_never_started_waiting_unit_is_not_counted() -> None:
    graph = [parked("one/1"), new_unit("waiting/1", depends_on=("one/1",))]

    assert not in_progress(graph[1], graph)
    assert start_room(graph, LIMIT, "app", account_of) == 1


def test_max_concurrent_stacks_counts_parked_units_by_project_not_by_account() -> None:
    """Two parked units of `app` fill a cap of 2 workers for `app`; a unit of `platform`, on the
    same account, has its own project's workers."""
    graph = [
        parked("one/1"),
        parked("two/1"),
        new_unit("three/1"),
        new_unit("four/1", repo="platform"),
    ]

    started = ready_units(
        graph,
        max_concurrent=2,
        depth_cap=9,
        max_units_in_progress=9,
        slot_of=lambda _: "kit",
        slot_limit=lambda _: 9,
    )

    assert [unit.id for unit in started] == ["four/1"]
