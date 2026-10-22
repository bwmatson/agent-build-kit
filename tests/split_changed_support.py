"""Parked units whose group's `Split:` was edited (spec: a-parked-unit-follows-its-groups-split):
the tasks file the groups are read from, and the thread a rework is delivered to."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli.pipeline import Resumed
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, UnitOutcome
from agent_build_kit.pipeline.unit_store import Cause, UnitStore, guidance_excerpt
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.graph_driver import tick
from tests.parked_split_support import Deliveries
from tests.runner_fakes import Recorder
from tests.split_workspace import group, tasks_text

__all__ = ["UNIT", "Reworks", "deliver_to_graph", "park_after_tick", "write_split"]

UNIT = "feature/1"


def write_split(inst: Installation, *splits: str | None, change: str = "feature") -> None:
    """The change's tasks file: one e2e-test group for each entry, saying `Split: <entry>`, or
    no `Split:` line for None."""
    path = inst.changes_dir / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        tasks_text(*(group(n, *([f"Split: {s}"] if s else [])) for n, s in enumerate(splits, 1)))
    )


def park_after_tick(store: UnitStore, unit_id: str, *splits: str) -> None:
    """Park the unit on the splits as the e2e step leaves it after a tick: no pull request, not
    pushed or approved (the fake forge opened one on the way), `planned` with cause `split_held`."""
    payload = json.loads(store.path.read_text())
    for record in payload["units"]:
        record.update(pr=None, pushed="", approved="")
    store.path.write_text(json.dumps(payload))
    store.set_state(unit_id, PLANNED, cause=Cause.SPLIT_HELD, note="e2e tests of acp did not run")
    store.set_parked(unit_id, splits, "abc1234", "snapshot")


def deliver_to_graph(
    tmp_path: Path, recorder: Recorder, tier: str | None = None, **overrides: Any
) -> Callable[..., Resumed]:
    """A replacement for `resume_thread` that hands the delivery to the graph as a resume event
    and runs a tick with it, in `tier` when given and with the tick's `overrides`."""
    options: dict[str, Any] = {**overrides, **({} if tier is None else {"tier": tier})}

    def deliver(inst: Installation, stored: Any, kind: str, **kwargs: Any) -> Resumed:
        event = ResumeEvent(
            kind=EventKind(kind),
            reason=kwargs["reason"],
            guidance=kwargs.get("guidance", ""),
            requeue=kwargs["requeue"],
        )
        return Resumed(outcome=tick(tmp_path, recorder, event=event, **options))

    return deliver


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
            unit.id,
            RUNNING,
            note=f"requeued: {kwargs.get('reason', '')}"
            + guidance_excerpt(kwargs.get("guidance", "")),
            cause=Cause.REQUEUED,
        )
        return Resumed(outcome=RunOutcome(status=UnitOutcome.OPEN, detail="waiting for the tick"))
