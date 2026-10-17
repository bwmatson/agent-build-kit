"""What the tests of a failed unit's requeue at the end of its wait share: a unit store, a
fake host that takes the delivery to a thread, and the passes that record and detect.

The host is faked where the pipeline hands an event to a unit's thread (`resume_thread`);
everything before that, the store, the graph and the mode rule, is the real one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, UnitOutcome
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import FAILED, MERGED, RUNNING
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conftest import make_installation
from tests.factories import new_unit

PARENT = "base/1"
CHILD = "kid/1"
WAIT_ENDED = "its wait ended"


@dataclass
class Host:
    """The threads a pass delivers to: every delivery is recorded, and `busy` makes the
    branch be held by another run. A delivery leaves the unit running with the history
    entry the thread's wait node writes for a requeue (`requeue: <reason>`)."""

    store: UnitStore
    threads: bool = True
    busy: bool = False
    deliveries: list[dict[str, Any]] = field(default_factory=list)

    def resume_thread(self, inst: Installation, unit: Any, kind: str, **kwargs: Any) -> Any:
        if not self.threads:
            return None
        if self.busy:
            raise BranchBusy(unit.branch)
        self.deliveries.append({"unit": unit.id, "kind": kind, **kwargs})
        self.store.set_state(
            unit.id, RUNNING, note=f"requeue: {kwargs['reason']}", cause=Cause.REQUEUED
        )
        return cli.Resumed(outcome=RunOutcome(status=UnitOutcome.WAITING, detail="queued"))


@dataclass
class Pipeline:
    inst: Installation
    store: UnitStore
    host: Host

    def pass_(self, *, in_flight: tuple[str, ...] = ()) -> None:
        """One pass of the step that records a wait and requeues a unit whose wait ended."""
        cli.requeue_wait_ended(self.inst, self.store, in_flight=in_flight)

    def passes(self, count: int) -> None:
        for _ in range(count):
            self.pass_()

    def waiting_failed(self, *parents: str, uid: str = CHILD) -> None:
        """`uid` failed and waits on `parents` (default: the running parent). Every unit is
        upserted together, since an upsert marks a unit the plan lacks as unplanned."""
        waits = parents or (PARENT,)
        self.store.upsert(
            [*(new_unit(parent) for parent in waits), new_unit(uid, depends_on=waits)]
        )
        for parent in waits:
            self.store.set_state(parent, RUNNING, branch=f"spec/{parent}")
        self.store.set_state(uid, FAILED, branch=f"spec/{uid}", cause=Cause.FAILED)

    def merge(self, *uids: str) -> None:
        for uid in uids or (PARENT,):
            self.store.set_state(uid, MERGED, pr=1)

    def wait_ended_notes(self, uid: str = CHILD) -> list[str]:
        return [
            entry["note"]
            for entry in self.store.get(uid).history
            if WAIT_ENDED in entry.get("note", "")
        ]


def pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    threads: bool = True,
    wait_end_requeue: str | None = None,
    **overrides: Any,
) -> Pipeline:
    """An installation, its store and a fake host. `wait_end_requeue` is the
    `global_limits` setting; the rest are installation sections."""
    if wait_end_requeue is not None:
        overrides["global_limits"] = {"wait_end_requeue": wait_end_requeue}
    inst = make_installation(tmp_path / "planning", **overrides)
    store = UnitStore(inst.state_dir / "units.json")
    host = Host(store, threads=threads)
    monkeypatch.setattr(cli, "has_thread", lambda _inst, _uid: host.threads)
    monkeypatch.setattr(cli, "resume_thread", host.resume_thread)
    return Pipeline(inst, store, host)


def save_failure(
    pipe: Pipeline,
    uid: str = CHILD,
    *,
    feedback: str = "",
    source: FeedbackSource = FeedbackSource.NONE,
    cause: Cause = Cause.FAILED,
    guidance: str = "",
) -> None:
    """What the failed unit's record holds when its wait begins."""
    pipe.store.set_state(uid, FAILED, branch=f"spec/{uid}", cause=cause)
    pipe.store.set_feedback(uid, feedback, source=source)
    if guidance:
        pipe.store.set_guidance(uid, guidance)


def mode_chosen(pipe: Pipeline) -> str:
    """Wait, end the wait, and say the mode the one delivery was made in."""
    pipe.pass_()
    pipe.merge()
    pipe.pass_()
    [delivery] = pipe.host.deliveries
    return "rework" if delivery["requeue"] is RequeueReason.FROM_FAILURE else "resume"
