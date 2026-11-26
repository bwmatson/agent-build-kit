"""The units store's contract, on the in-memory stand-in."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from agent_build_kit.orchestration.stand_in import InMemoryUnitsStore
from agent_build_kit.orchestration.store import (
    StoreConflict,
    StoredUnit,
    UnitsStore,
    VersionConflict,
)


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def drive[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a stand-in call to completion from inside a synchronous function the store is
    calling: the stand-in awaits no real I/O, so this is a second writer acting at that point."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("the stand-in awaited real I/O")


@pytest.fixture
def store() -> UnitsStore:
    return InMemoryUnitsStore()


def test_a_missing_unit_reads_as_none(store: UnitsStore) -> None:
    assert run(store.get("feature/1")) is None


def test_put_if_at_version_zero_creates_the_unit_at_version_one(store: UnitsStore) -> None:
    written = run(store.put_if("feature/1", {"state": "planned"}, 0))

    assert (written.id, written.version, written.body) == ("feature/1", 1, {"state": "planned"})
    assert run(store.get("feature/1")) == written


def test_two_writers_racing_on_version_three_get_one_success_and_one_conflict(
    store: UnitsStore,
) -> None:
    for version in range(3):
        run(store.put_if("u", {"n": version}, version))

    winner = run(store.put_if("u", {"n": "first"}, 3))
    with pytest.raises(VersionConflict):
        run(store.put_if("u", {"n": "second"}, 3))

    assert winner.version == 4
    assert run(store.get("u")) == winner


def test_put_if_at_version_zero_conflicts_when_the_unit_exists(store: UnitsStore) -> None:
    run(store.put_if("u", {}, 0))

    with pytest.raises(VersionConflict):
        run(store.put_if("u", {}, 0))


def test_list_returns_every_unit_ordered_by_id(store: UnitsStore) -> None:
    for unit_id in ("b/1", "a/2", "a/1"):
        run(store.put_if(unit_id, {"id": unit_id}, 0))

    assert [u.id for u in run(store.list())] == ["a/1", "a/2", "b/1"]


def test_update_applies_the_function_to_the_stored_body(store: UnitsStore) -> None:
    run(store.put_if("u", {"n": 1}, 0))

    updated = run(store.update("u", lambda body: {**body, "n": body["n"] + 1}))

    assert (updated.body, updated.version) == ({"n": 2}, 2)


def test_update_applies_the_function_to_the_newer_unit_when_another_writer_changes_it(
    store: UnitsStore,
) -> None:
    run(store.put_if("u", {"n": 1}, 0))
    seen: list[int] = []

    def fn(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body["n"])
        if len(seen) == 1:
            drive(store.put_if("u", {"n": 5}, 1))  # the other writer lands mid-update
        return {"n": body["n"] + 10}

    result = run(store.update("u", fn))

    assert seen == [1, 5]
    assert (result.body, result.version) == ({"n": 15}, 3)


def test_update_raises_a_conflict_after_the_given_attempts_when_the_unit_keeps_changing(
    store: UnitsStore,
) -> None:
    run(store.put_if("u", {"n": 0}, 0))
    calls = 0

    def always_raced(body: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        current: StoredUnit | None = drive(store.get("u"))
        assert current is not None
        drive(store.put_if("u", {"n": body["n"] + 1}, current.version))
        return {"n": -1}

    with pytest.raises(StoreConflict):
        run(store.update("u", always_raced, attempts=3))

    assert calls == 3


def test_history_entries_keep_the_order_they_were_appended_in(store: UnitsStore) -> None:
    run(store.put_if("u", {}, 0))
    sequences = [run(store.append_history("u", {"event": e})) for e in ("a", "b", "c")]

    assert sequences == [1, 2, 3]
    assert run(store.history("u")) == [{"event": "a"}, {"event": "b"}, {"event": "c"}]


def test_history_is_kept_per_unit(store: UnitsStore) -> None:
    run(store.append_history("a", {"event": "x"}))
    run(store.append_history("b", {"event": "y"}))

    assert run(store.history("a")) == [{"event": "x"}]
