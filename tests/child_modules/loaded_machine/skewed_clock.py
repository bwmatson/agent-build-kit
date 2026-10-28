"""A pytest plugin that makes the machine look loaded to the one file under test.

Each read of `time.monotonic` from `tests/runtimes/test_acp_outcome.py` returns a value
`SKEW` seconds later than the read before it, so a test in that file which measures how long
a run took, and bounds it, sees a run that took far longer than it did. Every other caller of
the clock, such as the event loop the run uses, reads it as before. The caller is matched by
its file, not its module name, which depends on pytest's import mode. The run's summary says
how many reads were skewed, so a parent can tell the skew happened.
"""

import sys
import time
from pathlib import Path

import pytest

from tests.tracked_files import ROOT

SKEW = 8.0
TARGET = (ROOT / "tests/runtimes/test_acp_outcome.py").resolve()
REAL = time.monotonic
SKEWED = [0]


@pytest.fixture(autouse=True)
def loaded_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    def monotonic() -> float:
        if Path(sys._getframe(1).f_code.co_filename).resolve() != TARGET:
            return REAL()
        SKEWED[0] += 1
        return REAL() + SKEW * SKEWED[0]

    monkeypatch.setattr(time, "monotonic", monotonic)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    terminalreporter.write_line(f"skewed reads: {SKEWED[0]}")
