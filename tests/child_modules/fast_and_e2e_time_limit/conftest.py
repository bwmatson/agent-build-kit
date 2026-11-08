import time
from collections.abc import Callable

import pytest

from tests.cpu_spin import busy_cpu, make_backstop_unreachable

make_backstop_unreachable()


def busy_wait(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pass


@pytest.fixture(scope="session")
def spin() -> Callable[[float], None]:
    """Spins for wall time: for an e2e test, which has only a wall limit."""
    return busy_wait


@pytest.fixture(scope="session")
def spin_cpu() -> Callable[[float], None]:
    """Spins until the process has used that much CPU: for a test held to a CPU budget."""
    return busy_cpu
