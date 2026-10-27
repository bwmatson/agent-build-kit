import os
import threading
from collections.abc import Iterator
from typing import Any

import pytest

REAL_TIMER = threading.Timer
FIRE_FIRST = os.environ.get("CHILD_FIRE_FIRST_TIMER") == "1"


@pytest.fixture(autouse=True)
def armed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    intervals: list[float] = []

    class Recording(REAL_TIMER):
        def __init__(self, interval: float, *args: Any, **kwargs: Any) -> None:
            first = not intervals
            intervals.append(interval)
            super().__init__(0 if FIRE_FIRST and first else interval, *args, **kwargs)

    monkeypatch.setattr(threading, "Timer", Recording)
    yield intervals
