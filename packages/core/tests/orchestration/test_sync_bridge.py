"""The transitional bridge: synchronous callers reach the async `UnitsStore` through `run_store`."""

from __future__ import annotations

import asyncio
import threading

import pytest

from agent_build_kit.orchestration.sync_bridge import run_store


async def answer(value: int) -> int:
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
