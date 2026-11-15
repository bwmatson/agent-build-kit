import asyncio

import pytest


async def spin_until_stopped() -> None:
    try:
        while True:
            sum(range(1000))
    finally:
        raise RuntimeError("replaced while unwinding")


@pytest.mark.time_limit(1)
def test_trips_inside_asyncio_run() -> None:
    asyncio.run(spin_until_stopped())
