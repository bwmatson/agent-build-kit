"""The units store's conformance suite: the cases every `UnitsStore` implementation must pass.

An implementation's test module parametrizes over `CASES` and calls `run_case` with a factory
that makes a fresh `Harness`. The racing writers are real tasks (`asyncio.gather`), and the one
case that needs a writer to land between a read and a write goes through `Harness.write_behind`,
a synchronous second writer the implementation's test supplies, so no case relies on how an
implementation schedules its awaits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from pydantic import ConfigDict, SkipValidation

from agent_build_kit.model import Frozen
from agent_build_kit.orchestration.store import (
    StoreConflict,
    UnitNotFound,
    UnitsStore,
    VersionConflict,
)


async def _nothing_to_close() -> None:
    return None


class Harness(Frozen):
    """A store under test, and a way for another writer to change it behind its back."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    store: SkipValidation[UnitsStore]
    # (unit id, body, version the unit is at): stores the body at version + 1, synchronously.
    write_behind: Callable[[str, dict[str, Any], int], None]
    # Releases what the store holds (engines, connections); `run_case` awaits it in the case's
    # own event loop once the case is done, however it ended.
    close: Callable[[], Coroutine[Any, Any, None]] = _nothing_to_close


HarnessFactory = Callable[[], Harness]
Case = Callable[[Harness], Coroutine[Any, Any, None]]


async def _a_missing_unit_reads_as_none(h: Harness) -> None:
    assert await h.store.get("feature/1") is None


async def _put_if_at_version_zero_creates_the_unit_at_version_one(h: Harness) -> None:
    written = await h.store.put_if("feature/1", {"state": "planned"}, 0)

    assert (written.id, written.version, written.body) == ("feature/1", 1, {"state": "planned"})
    assert await h.store.get("feature/1") == written


async def _put_if_at_version_zero_conflicts_when_the_unit_exists(h: Harness) -> None:
    await h.store.put_if("u", {}, 0)

    with pytest.raises(VersionConflict):
        await h.store.put_if("u", {}, 0)


async def _put_if_with_a_stale_version_conflicts_and_leaves_the_unit(h: Harness) -> None:
    await h.store.put_if("u", {"n": 1}, 0)
    await h.store.put_if("u", {"n": 2}, 1)

    with pytest.raises(VersionConflict):
        await h.store.put_if("u", {"n": 99}, 1)

    stored = await h.store.get("u")
    assert stored is not None and (stored.body, stored.version) == ({"n": 2}, 2)


async def _two_writers_racing_on_version_three_get_one_success_and_one_conflict(
    h: Harness,
) -> None:
    for version in range(3):
        await h.store.put_if("u", {"n": version}, version)

    results = await asyncio.gather(
        h.store.put_if("u", {"n": "first"}, 3),
        h.store.put_if("u", {"n": "second"}, 3),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, BaseException)]
    assert len(winners) == 1 and len(losers) == 1
    assert isinstance(losers[0], VersionConflict)
    stored = await h.store.get("u")
    assert stored is not None and stored == winners[0] and stored.version == 4


async def _list_returns_every_unit_ordered_by_id(h: Harness) -> None:
    for unit_id in ("b/1", "a/2", "a/1"):
        await h.store.put_if(unit_id, {"id": unit_id}, 0)

    assert [u.id for u in await h.store.list()] == ["a/1", "a/2", "b/1"]


async def _update_applies_the_function_to_the_stored_body(h: Harness) -> None:
    await h.store.put_if("u", {"n": 1}, 0)

    updated = await h.store.update("u", lambda body: {**body, "n": body["n"] + 1})

    assert (updated.body, updated.version) == ({"n": 2}, 2)


async def _update_of_a_missing_unit_raises(h: Harness) -> None:
    with pytest.raises(UnitNotFound):
        await h.store.update("never-stored", lambda body: body)

    assert await h.store.get("never-stored") is None


async def _update_applies_the_function_to_the_newer_unit_when_another_writer_changes_it(
    h: Harness,
) -> None:
    await h.store.put_if("u", {"n": 1}, 0)
    seen: list[int] = []

    def fn(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body["n"])
        if len(seen) == 1:
            h.write_behind("u", {"n": 5}, 1)  # the other writer lands mid-update
        return {"n": body["n"] + 10}

    result = await h.store.update("u", fn)

    assert seen == [1, 5]
    assert (result.body, result.version) == ({"n": 15}, 3)


async def _update_raises_a_conflict_after_the_given_attempts_when_the_unit_keeps_changing(
    h: Harness,
) -> None:
    await h.store.put_if("u", {"n": 0}, 0)
    calls = 0

    def always_raced(body: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        h.write_behind("u", {"n": body["n"] + 1}, calls)
        return {"n": -1}

    with pytest.raises(StoreConflict):
        await h.store.update("u", always_raced, attempts=3)

    assert calls == 3


async def _concurrent_updates_each_apply_once(h: Harness) -> None:
    await h.store.put_if("u", {"n": 0}, 0)

    await asyncio.gather(
        *(h.store.update("u", lambda b: {"n": b["n"] + 1}, attempts=20) for _ in range(4))
    )

    stored = await h.store.get("u")
    assert stored is not None and (stored.body, stored.version) == ({"n": 4}, 5)


async def _history_entries_keep_the_order_they_were_appended_in(h: Harness) -> None:
    await h.store.put_if("u", {}, 0)
    sequences = [await h.store.append_history("u", {"event": e}) for e in ("a", "b", "c")]

    assert sequences == [1, 2, 3]
    assert await h.store.history("u") == [{"event": "a"}, {"event": "b"}, {"event": "c"}]


async def _history_is_kept_per_unit(h: Harness) -> None:
    await h.store.put_if("a", {}, 0)
    await h.store.put_if("b", {}, 0)
    await h.store.append_history("a", {"event": "x"})
    await h.store.append_history("b", {"event": "y"})

    assert await h.store.history("a") == [{"event": "x"}]


async def _appending_history_to_a_missing_unit_raises(h: Harness) -> None:
    with pytest.raises(UnitNotFound):
        await h.store.append_history("never-stored", {"event": "x"})


CASES: dict[str, Case] = {
    "a_missing_unit_reads_as_none": _a_missing_unit_reads_as_none,
    "put_if_at_version_zero_creates_the_unit_at_version_one": (
        _put_if_at_version_zero_creates_the_unit_at_version_one
    ),
    "put_if_at_version_zero_conflicts_when_the_unit_exists": (
        _put_if_at_version_zero_conflicts_when_the_unit_exists
    ),
    "put_if_with_a_stale_version_conflicts_and_leaves_the_unit": (
        _put_if_with_a_stale_version_conflicts_and_leaves_the_unit
    ),
    "two_writers_racing_get_one_success_and_one_conflict": (
        _two_writers_racing_on_version_three_get_one_success_and_one_conflict
    ),
    "list_returns_every_unit_ordered_by_id": _list_returns_every_unit_ordered_by_id,
    "update_applies_the_function_to_the_stored_body": (
        _update_applies_the_function_to_the_stored_body
    ),
    "update_of_a_missing_unit_raises": _update_of_a_missing_unit_raises,
    "update_retries_against_a_concurrent_change": (
        _update_applies_the_function_to_the_newer_unit_when_another_writer_changes_it
    ),
    "update_raises_a_conflict_after_the_given_attempts": (
        _update_raises_a_conflict_after_the_given_attempts_when_the_unit_keeps_changing
    ),
    "concurrent_updates_each_apply_once": _concurrent_updates_each_apply_once,
    "history_entries_keep_their_order": _history_entries_keep_the_order_they_were_appended_in,
    "history_is_kept_per_unit": _history_is_kept_per_unit,
    "appending_history_to_a_missing_unit_raises": _appending_history_to_a_missing_unit_raises,
}


def run_case(name: str, factory: HarnessFactory) -> None:
    """Run the named case against a fresh harness from `factory`, then close the harness in the
    same event loop."""

    harness = factory()  # outside the loop: a factory may run the migrations, which start one

    async def run() -> None:
        try:
            await CASES[name](harness)
        finally:
            await harness.close()

    asyncio.run(run())
