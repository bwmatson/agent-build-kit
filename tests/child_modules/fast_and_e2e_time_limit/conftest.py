import time
from collections.abc import Callable

import pytest


def busy_wait(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pass


@pytest.fixture(scope="session")
def spin() -> Callable[[float], None]:
    return busy_wait
