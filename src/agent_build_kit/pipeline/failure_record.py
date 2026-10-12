"""A record of tests that failed, appended to a jsonl file in the state directory.

One implementation for every kind of failing test the pipeline keeps a record of (flaky,
pre-existing): the entry model differs, how it is stored and counted does not.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock


class Recorded(Frozen):
    """What every kind of entry has: the test, and the change that fixes it once there is one."""

    test: str
    change: str = ""


class TestCount(Frozen):
    """A test, how many entries it has and the latest change that fixes it."""

    __test__ = False

    test: str
    count: int
    change: str


class FailureRecord[T: Recorded]:
    """The entries of one kind, in a file of their own with a lock beside it."""

    def __init__(self, path: Path, model: type[T]) -> None:
        self.path = path
        self._model = model

    def append(self, entry: T) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json() + "\n")

    def entries(self) -> list[T]:
        """Every entry recorded, oldest first."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        return [self._model.model_validate_json(line) for line in lines if line.strip()]

    def counts(self) -> list[TestCount]:
        """Each test once, with how often it was recorded and its latest fix change."""
        counted: dict[str, TestCount] = {}
        for entry in self.entries():
            before = counted.get(entry.test)
            counted[entry.test] = TestCount(
                test=entry.test,
                count=(before.count if before else 0) + 1,
                change=entry.change or (before.change if before else ""),
            )
        return list(counted.values())
