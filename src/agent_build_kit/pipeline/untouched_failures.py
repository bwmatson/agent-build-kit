"""A test that fails tier 2 on the base too: recorded, and fixed once by its own change.

Stubs: the record, the preview and the ensure step are not written yet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock  # noqa: F401
from agent_build_kit.pipeline.unit_store import StoredUnit


class PreExisting(Frozen):
    """One test that failed tier 2 for a unit and failed on the base as well."""

    test: str
    unit: str
    command: str
    line: str
    at: datetime
    base_result: str = "failed"
    base_output: str = ""
    change: str = ""


class PreExistingCount(Frozen):
    """A pre-existing failing test, how many times it failed on the base and its fix change."""

    test: str
    count: int
    change: str


class PreExistingRecord:
    """The pre-existing failures found, appended to a file in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, entry: PreExisting) -> None:
        raise NotImplementedError

    def entries(self) -> list[PreExisting]:
        raise NotImplementedError

    def counts(self) -> list[PreExistingCount]:
        raise NotImplementedError


def preexisting_record(inst: Installation) -> PreExistingRecord:
    raise NotImplementedError


class Exists(Frozen):
    """The open change that already fixes a test."""

    change: str


class Write(Frozen):
    """The change that would be written for a test, and the archived attempt before it."""

    name: str
    earlier: str = ""


def preview(inst: Installation, test: str) -> Exists | Write:
    """What the ensure step would do for `test`; reads the changes directory only."""
    raise NotImplementedError


def ensure_fix(
    inst: Installation, entry: PreExisting, unit: StoredUnit, *, say: Callable[[str], None]
) -> str:
    """Make sure one open change fixes `entry.test`: say `exists: <change>`, or
    `would write: <change>` then `wrote: <change>`. Returns the change's name."""
    raise NotImplementedError
