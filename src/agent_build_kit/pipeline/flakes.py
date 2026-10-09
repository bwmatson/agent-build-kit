"""A flaky test: told from a failure by running it alone, recorded, and fixed once.

When tier 1 fails on tests, the failed tests are run again serially. A test that fails
again is a failure. One that passes both reruns is a flake: it is recorded, it gets one
change that makes it deterministic, and every unit that met it waits on that change.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit


class Flake(Frozen):
    """One test that failed under load and passed alone."""

    test: str
    command: str
    output: str
    at: datetime
    # Set by whoever records it: tier 1 does not know which unit it ran for.
    unit: str = ""
    # The change that fixes the test, once there is one.
    change: str = ""


class FlakeFound(Exception):
    """Raised by tier 1 when every failed test passed both serial reruns: the unit is not
    failed for them, it waits for their fix."""

    def __init__(self, flakes: tuple[Flake, ...]) -> None:
        super().__init__(", ".join(flake.test for flake in flakes))
        self.flakes = flakes


class FlakeCount(Frozen):
    """A flaky test, how many times it flaked and the change that fixes it."""

    test: str
    count: int
    change: str


class FlakeRecord:
    """The flakes found, appended to a file in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, flake: Flake) -> None:
        raise NotImplementedError

    def entries(self) -> list[Flake]:
        """Every flake recorded, oldest first."""
        raise NotImplementedError

    def counts(self) -> list[FlakeCount]:
        """Each flaky test once, with how often it flaked and its latest fix change."""
        raise NotImplementedError


def flake_record(inst: Installation) -> FlakeRecord:
    raise NotImplementedError


def flake_change_name(test: str) -> str:
    """The name of the change that fixes `test`, from its identifier: lower-case words
    joined by hyphens, the same for the same test."""
    raise NotImplementedError


def wait_on_fix(inst: Installation, flake: Flake, unit: StoredUnit) -> str | None:
    """Make sure the one open change that fixes `flake.test` exists, under the state
    directory's lock, and give each group of `unit` a `Needs:` line on it. Returns the
    change's name, or None for a unit of that change itself, which waits on nothing."""
    raise NotImplementedError
