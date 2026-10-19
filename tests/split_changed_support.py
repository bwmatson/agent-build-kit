"""Parked units whose group's `Split:` was edited (spec: a-parked-unit-follows-its-groups-split):
the tasks file the groups are read from, and the thread a rework is delivered to."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.parked_split_support import Deliveries
from tests.split_workspace import group, tasks_text

__all__ = ["UNIT", "Reworks", "release", "write_split"]

UNIT = "feature/1"


def write_split(inst: Installation, *splits: str | None, change: str = "feature") -> None:
    """The change's tasks file: one e2e-test group for each entry, saying `Split: <entry>`, or
    no `Split:` line for None."""
    path = inst.changes_dir / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        tasks_text(*(group(n, *([f"Split: {s}"] if s else [])) for n, s in enumerate(splits, 1)))
    )


class Reworks(Deliveries):
    """The thread a rework is delivered to. A delivery runs the requeue handler's store write
    (the unit is `running`, cause `requeued`) and keeps the arguments it was handed; with
    `thread=False` there is none, as for a unit that has no thread."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, store: UnitStore, *, thread: bool = True
    ) -> None:
        super().__init__(monkeypatch)
        self.store = store
        self.thread = thread
        self.calls: list[dict[str, Any]] = []

    def resume(self, inst: Installation, unit: Any, kind: str, **kwargs: Any) -> Any:
        super().resume(inst, unit, kind, **kwargs)
        self.calls.append({"unit": unit.id, "kind": kind, **kwargs})
        if not self.thread:
            return None
        self.store.set_state(
            unit.id, RUNNING, note=f"requeued: {kwargs.get('reason', '')}", cause=Cause.REQUEUED
        )
        return object()


def release(inst: Installation, store: UnitStore, **kwargs: Any) -> None:
    """One pass of the step."""
    cli.release_split_changed(inst, store, **kwargs)
