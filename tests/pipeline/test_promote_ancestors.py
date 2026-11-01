"""An unstarted unit takes the urgency of every unit that waits on it, and says whose.

Each unit `c/N` builds group N of change `c`, whose priority is the catalog's; the store
holds the units as a plan left them, at the default priority.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_build_kit.pipeline.planner import promote_ancestors
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import CLOSED, MERGED, RUNNING, SATISFIED, Priority, UnitState
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import groups_at, unit


def catalog(*priorities: int) -> Mapping[str, Sequence[TaskGroup]]:
    return {"c": groups_at(*priorities)}


def stored(tmp_path, *edges: tuple[int, tuple[int, ...]]) -> UnitStore:
    """Units c/N for each `(N, groups it depends on)`, as a plan leaves them."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit(
                f"c/{number}", change="c", groups=(number,), depends_on=tuple(f"c/{n}" for n in on)
            )
            for number, on in edges
        ]
    )
    return store


def result(store: UnitStore, number: int) -> tuple[int, str]:
    found = store.get(f"c/{number}")
    return found.priority, found.promoted_from


def test_an_unstarted_prerequisite_takes_the_priority_of_an_unstarted_dependent(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))

    promote_ancestors(store, catalog(3, 1))

    assert result(store, 1) == (1, "c/2")
    assert result(store, 2) == (1, "")


def test_through_a_chain_of_three_the_first_takes_it_from_the_last(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (2,)))

    promote_ancestors(store, catalog(5, 3, 1))

    assert result(store, 1) == (1, "c/3")
    assert result(store, 2) == (1, "c/3")
    assert result(store, 3) == (1, "")


def test_of_two_equally_urgent_waiters_the_id_that_sorts_first_is_named(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (3, (1,)), (2, (1,)))

    promote_ancestors(store, catalog(3, 1, 1))

    assert result(store, 1) == (1, "c/2")


def test_a_waiter_of_equal_or_lower_urgency_changes_nothing(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (1,)))
    # Stored as the planning pass leaves them: each at the priority of its group.
    for number, priority in ((1, 2), (2, 2), (3, 4)):
        store.set_priority(f"c/{number}", priority)
    before = store.path.read_text()

    promote_ancestors(store, catalog(2, 2, 4))

    assert result(store, 1) == (2, "")
    assert store.path.read_text() == before


def test_a_started_prerequisite_keeps_its_priority_and_its_source(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (1,)))
    store.set_promotion("c/3", 2, "c/9")
    store.set_state("c/3", RUNNING, branch="spec/c/3")
    store.set_state("c/1", RUNNING, branch="spec/c/1")

    promote_ancestors(store, catalog(3, 1, 3))

    assert result(store, 1) == (3, "")
    assert result(store, 3) == (2, "c/9")


def test_an_unstarted_prerequisite_is_promoted_by_a_started_waiter_at_its_stored_priority(
    tmp_path,
) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    store.upsert([unit("c/2", change="c", groups=(2,), depends_on=("c/1",), priority=1)])
    store.set_state("c/2", RUNNING, branch="spec/c/2")

    promote_ancestors(store, catalog(3, 3))

    assert result(store, 1) == (1, "c/2")
    assert result(store, 2) == (1, "")


def test_a_second_pass_writes_nothing(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (2,)))
    promote_ancestors(store, catalog(5, 3, 1))
    written = store.path.read_text()
    assert result(store, 1) == (1, "c/3")

    promote_ancestors(store, catalog(5, 3, 1))

    assert store.path.read_text() == written


def test_a_merged_or_closed_waiter_gives_nothing(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (1,)))
    store.set_state("c/2", MERGED, branch="spec/c/2", pr=2)
    store.set_state("c/3", CLOSED, branch="spec/c/3", pr=3)

    promote_ancestors(store, catalog(3, 1, 1))

    assert result(store, 1) == (3, "")


def test_an_unplanned_waiter_gives_nothing(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    store.set_state("c/2", UnitState.UNPLANNED)

    promote_ancestors(store, catalog(3, 1))

    assert result(store, 1) == (3, "")


def test_a_satisfied_waiter_is_looked_through_to_what_waits_on_it(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)), (3, (2,)))
    store.set_state("c/2", SATISFIED)

    promote_ancestors(store, catalog(3, 1, 2))

    assert result(store, 1) == (2, "c/3")


def test_a_promotion_lapses_at_the_pass_after_its_waiter_merges(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    promote_ancestors(store, catalog(3, 1))
    assert result(store, 1) == (1, "c/2")
    store.set_state("c/2", MERGED, branch="spec/c/2", pr=2)

    promote_ancestors(store, catalog(3, 1))

    assert result(store, 1) == (3, "")


def test_a_promotion_lapses_at_the_pass_after_its_waiter_loses_the_edge(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    promote_ancestors(store, catalog(3, 1))
    assert result(store, 1) == (1, "c/2")
    store.upsert([unit("c/2", change="c", groups=(2,))])

    promote_ancestors(store, catalog(3, 1))

    assert result(store, 1) == (3, "")


def test_a_promoted_unit_whose_groups_are_not_in_the_catalog_falls_back_to_normal_on_lapse(
    tmp_path,
) -> None:
    store = stored(tmp_path, (1, ()))
    store.set_promotion("c/1", 0, "c/2")

    promote_ancestors(store, {})

    assert result(store, 1) == (3, "")


def test_an_unpromoted_unit_whose_groups_are_not_in_the_catalog_keeps_its_stored_priority(
    tmp_path,
) -> None:
    store = stored(tmp_path, (1, ()))
    store.set_promotion("c/1", 1, "")

    promote_ancestors(store, {})

    assert result(store, 1) == (1, "")


def test_a_unit_that_started_while_promoted_keeps_the_promoted_priority_and_source(
    tmp_path,
) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    promote_ancestors(store, catalog(3, 1))
    assert result(store, 1) == (1, "c/2")
    store.set_state("c/1", RUNNING, branch="spec/c/1")
    store.set_state("c/2", MERGED, branch="spec/c/2", pr=2)

    promote_ancestors(store, catalog(3, 1))

    assert result(store, 1) == (1, "c/2")


def reads_by_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, units: int) -> int:
    """How many times a pass over `units` independent units, each already at the priority of
    its group, reads the store file."""
    folder = tmp_path / str(units)
    folder.mkdir()
    store = stored(folder, *((number, ()) for number in range(1, units + 1)))
    reads: list[Path] = []
    read_text = Path.read_text

    def counting(path: Path, *args, **kwargs) -> str:
        if path == store.path:
            reads.append(path)
        return read_text(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "read_text", counting)
        promote_ancestors(store, catalog(*([Priority.NORMAL] * units)))
    return len(reads)


def test_a_pass_reads_the_store_once_however_many_units_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    few = reads_by_a_pass(tmp_path, monkeypatch, 20)
    many = reads_by_a_pass(tmp_path, monkeypatch, 200)

    assert (few, many) == (1, 1), "the reads of the store file for 20 units and for 200"
