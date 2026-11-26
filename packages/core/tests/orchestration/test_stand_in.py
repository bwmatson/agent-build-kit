"""The units store's contract, on the in-memory stand-in.

The cases are the conformance suite's, shared with the SQL store. A second writer landing between
a read and a write is `drive`, which steps a call synchronously and so works only on this
stand-in, which never awaits."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from agent_build_kit.orchestration.stand_in import InMemoryUnitsStore
from tests.support.units_store_conformance import CASES, Harness, run_case


def drive[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a stand-in call to completion from inside a synchronous function the store is
    calling: the stand-in awaits no real I/O, so this is a second writer acting at that point."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("the stand-in awaited real I/O")


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_stand_in_passes_the_conformance_case(case: str) -> None:
    def factory() -> Harness:
        store = InMemoryUnitsStore()

        def write_behind(unit_id: str, body: dict[str, Any], version: int) -> None:
            drive(store.put_if(unit_id, body, version))

        return Harness(store=store, write_behind=write_behind)

    run_case(case, factory)


def test_mutating_a_returned_body_does_not_change_the_stored_unit() -> None:
    async def scenario() -> None:
        store = InMemoryUnitsStore()
        written = await store.put_if("u", {"n": 1}, 0)
        written.body["n"] = 99
        listed = await store.list()
        listed[0].body["n"] = 98

        stored = await store.get("u")
        assert stored is not None and stored.body == {"n": 1}

    asyncio.run(scenario())
