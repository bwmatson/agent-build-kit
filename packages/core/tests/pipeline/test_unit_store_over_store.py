"""`UnitStore` over the async units store, and the bridge that lets synchronous code call it.

The stand-in is the store behind `UnitStore` here; with no store given the file is the store, as
before."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.orchestration.stand_in import InMemoryUnitsStore
from agent_build_kit.orchestration.sync_bridge import run_store
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import stored_unit


def seed(store: UnitStore) -> None:
    store.upsert(
        [stored_unit("feature/1", change="feature", groups=(1,))]
        + [stored_unit("other/1", change="other", groups=(1,))]
    )


def stored_ids(backing: InMemoryUnitsStore) -> list[str]:
    """What the backing store holds, read straight from it and not through `UnitStore`."""
    return [row.id for row in asyncio.run(backing.list())]


class RacingStore(InMemoryUnitsStore):
    """A stand-in on which another writer changes a unit just after the first listing."""

    def __init__(self, racer: str) -> None:
        super().__init__()
        self.racer = racer
        self.raced = False

    async def list(self):  # noqa: ANN201
        listed = await super().list()
        if not self.raced:
            self.raced = True
            current = await self.get(self.racer)
            assert current is not None
            body: dict[str, Any] = {**current.body, "estimated_lines": 777}
            await self.put_if(self.racer, body, current.version)
        return listed


def test_units_upserted_over_the_store_are_read_back_by_get_and_all(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed(store)

    assert sorted(stored_ids(backing)) == ["feature/1", "other/1"]
    assert not (tmp_path / "units.json").exists()
    assert [unit.id for unit in store.all()] == ["feature/1", "other/1"]
    assert store.get("feature/1").change == "feature"


def test_a_state_change_over_the_store_is_seen_by_a_second_unit_store(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    first = UnitStore(tmp_path / "units.json", store=backing)
    seed(first)

    first.set_state("feature/1", RUNNING, branch="spec/feature/1")

    held = asyncio.run(backing.get("feature/1"))
    assert held is not None
    assert held.body["state"] == RUNNING
    second = UnitStore(tmp_path / "other.json", store=backing)
    assert second.get("feature/1").state == RUNNING
    assert second.get("feature/1").branch == "spec/feature/1"
    assert second.get("other/1").state != RUNNING


def test_a_unit_that_is_not_stored_raises_key_error_over_the_store(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed(store)
    assert stored_ids(backing) != []

    with pytest.raises(KeyError):
        store.get("missing/1")


def test_replace_if_unchanged_over_the_store_writes_the_differing_units(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed(store)
    base = {unit.id: unit for unit in store.all()}
    after = {**base, "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99})}
    after["feature/2"] = base["feature/1"].model_copy(update={"id": "feature/2"})

    moved = store.replace_if_unchanged(base, after)

    assert moved == []
    assert "feature/2" in stored_ids(backing)
    assert store.get("feature/1").estimated_lines == 99
    assert store.get("feature/2").id == "feature/2"
    assert store.get("other/1") == base["other/1"]


def test_replace_if_unchanged_over_the_store_writes_nothing_when_one_unit_moved(
    tmp_path: Path,
) -> None:
    backing = RacingStore("other/1")
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed(store)
    base = {unit.id: unit for unit in store.all()}
    after = {
        **base,
        "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99}),
        "other/1": base["other/1"].model_copy(update={"estimated_lines": 55}),
    }

    moved = store.replace_if_unchanged(base, after)

    assert backing.raced
    assert moved == ["other/1"]
    assert store.get("feature/1") == base["feature/1"]
    assert store.get("other/1").estimated_lines == 777


def test_with_no_store_the_file_is_the_store_and_a_given_store_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    plain = UnitStore(path)
    seed(plain)
    plain.set_state("feature/1", RUNNING, branch="spec/feature/1")
    assert UnitStore(path).get("feature/1").state == RUNNING

    over_empty_store = UnitStore(path, store=InMemoryUnitsStore())

    assert over_empty_store.all() == []
    assert [unit.id for unit in UnitStore(path).all()] == ["feature/1", "other/1"]


async def answer(value: int) -> int:
    await asyncio.sleep(0)
    return value


def test_run_store_runs_a_coroutine_from_synchronous_code() -> None:
    assert run_store(answer(7)) == 7


def test_run_store_runs_a_coroutine_from_a_thread_with_no_loop() -> None:
    results: list[int] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            results.append(run_store(answer(8)))
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(timeout=30)

    assert not thread.is_alive()
    assert errors == []
    assert results == [8]


def test_run_store_raises_when_called_inside_a_running_loop() -> None:
    async def inside() -> None:
        coro = answer(1)
        try:
            with pytest.raises(RuntimeError) as raised:
                run_store(coro)
            assert not isinstance(raised.value, NotImplementedError)
        finally:
            coro.close()

    asyncio.run(inside())
