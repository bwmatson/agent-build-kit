"""A pytest plugin that makes the machine look loaded to the one module under test.

Each read of `time.monotonic` from `tests.runtimes.test_acp_outcome` returns a value
`SKEW` seconds later than the read before it, so a test in that module which measures how long
a run took, and bounds it, sees a run that took far longer than it did. Every other caller of
the clock, such as the event loop the run uses, reads it as before.
"""

import sys
import time

import pytest

SKEW = 8.0
MODULE = "tests.runtimes.test_acp_outcome"
REAL = time.monotonic


@pytest.fixture(autouse=True)
def loaded_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = 0

    def monotonic() -> float:
        nonlocal reads
        if sys._getframe(1).f_globals.get("__name__") != MODULE:
            return REAL()
        reads += 1
        return REAL() + SKEW * reads

    monkeypatch.setattr(time, "monotonic", monotonic)
