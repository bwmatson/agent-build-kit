"""An environment whose `sync` and `check` are real child processes, so the
pipeline is driven through the argv it runs and nothing else.

Each command appends its name to a call log and reads switches from a control
folder: `check` fails while `broken` exists, and `sync` mends it while
`sync-repairs` exists. A test flips the switches the way a repaired or damaged
environment would change.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BROKEN_OUTPUT = "ModuleNotFoundError: No module named 'widget'"
SYNC_FAILED_OUTPUT = "error: no solution found for widget>=9"

_CHECK = f"""\
import pathlib, sys

control = pathlib.Path(sys.argv[1])
with (control / "calls.log").open("a") as log:
    log.write("check" + chr(10))
if (control / "broken").exists():
    print({BROKEN_OUTPUT!r})
    sys.exit(1)
"""

_SYNC = f"""\
import pathlib, sys

control = pathlib.Path(sys.argv[1])
with (control / "calls.log").open("a") as log:
    log.write("sync" + chr(10))
if (control / "sync-fails").exists():
    print({SYNC_FAILED_OUTPUT!r})
    sys.exit(1)
if (control / "sync-repairs").exists():
    (control / "broken").unlink(missing_ok=True)
"""


class FakeEnvironment:
    """The state of one environment, and what has been run against it."""

    def __init__(self, control: Path, *, inputs: tuple[str, ...] = ("manifest.toml",)) -> None:
        control.mkdir(parents=True, exist_ok=True)
        self.control = control
        self.inputs = list(inputs)

    def config(self) -> dict[str, Any]:
        """The `environment` section, for `make_installation(..., environment=...)`."""
        return {
            "sync": [sys.executable, "-c", _SYNC, str(self.control)],
            "check": [sys.executable, "-c", _CHECK, str(self.control)],
            "inputs": {"dependencies": self.inputs},
        }

    def calls(self) -> list[str]:
        log = self.control / "calls.log"
        return log.read_text().split() if log.exists() else []

    def note(self, name: str) -> None:
        """Put something else that happened into the call log, to order it among the commands."""
        with (self.control / "calls.log").open("a") as log:
            log.write(f"{name}\n")

    def clear(self) -> None:
        (self.control / "calls.log").unlink(missing_ok=True)

    def break_it(self, *, sync_repairs: bool = False) -> None:
        (self.control / "broken").write_text("")
        if sync_repairs:
            (self.control / "sync-repairs").write_text("")

    def fail_sync(self, *, failing: bool = True) -> None:
        if failing:
            (self.control / "sync-fails").write_text("")
        else:
            (self.control / "sync-fails").unlink(missing_ok=True)

    def mend(self) -> None:
        (self.control / "broken").unlink(missing_ok=True)
