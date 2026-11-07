import time
from collections.abc import Callable

import pytest

import tests.time_limit

# The wall backstop is out of reach, so a CPU-bound test meets its CPU budget at any load.
tests.time_limit.BACKSTOP_FACTOR = 10_000


def busy_wait(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pass


def busy_cpu(seconds: float) -> None:
    deadline = time.process_time() + seconds
    while time.process_time() < deadline:
        pass


@pytest.fixture(scope="session")
def spin() -> Callable[[float], None]:
    """Spins for wall time: for an e2e test, which has only a wall limit."""
    return busy_wait


@pytest.fixture(scope="session")
def spin_cpu() -> Callable[[float], None]:
    """Spins until the process has used that much CPU: for a test held to a CPU budget."""
    return busy_cpu
