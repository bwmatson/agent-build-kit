"""A ready unit that waits for a build slot leaves a `span` line in the usage
ledger, from the tick first seeing it ready but for a free slot to the worker
taking the unit's branch lock (spec: unit-time-accounting). Time is a fake clock
the builds advance."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.fake_clock import START, FakeClock, install, span_lines

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


def stored(uid: str, repo: str) -> StoredUnit:
    change, _, _ = uid.partition("/")
    return StoredUnit(
        id=uid,
        change=change,
        title=f"Build {uid}",
        repo=repo,
        tier="tier1",
        depends_on=(),
        estimated_lines=140,
        groups=(1,),
    )


class Build:
    """Stands in for `build_runner`: each build takes `seconds` of the fake clock."""

    def __init__(self, store: UnitStore, clock: FakeClock, seconds: float) -> None:
        self.store = store
        self.clock = clock
        self.seconds = seconds
        self.started: list[str] = []

    def __call__(self, unit, **kwargs) -> Build:
        return self

    def run(self, unit, *, base, graph) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.clock.advance(self.seconds)
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))


def workspace_of(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
    )


def test_a_unit_submitted_while_every_slot_is_busy_records_the_wait_as_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = install(monkeypatch)
    inst = workspace_of(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("first/1", "app"), stored("second/1", "platform")])
    build = Build(store, clock, seconds=30)
    monkeypatch.setattr(cli, "build_runner", build)

    with branch_lock("spec/other/1", root=inst.state_dir / "locks"):
        assert cli.cmd_tick(argparse.Namespace(dry_run=False), inst) == 0

    first, second = build.started
    waits = [s for s in span_lines(inst) if s.get("waited") == "slot"]
    (waited,) = [s for s in waits if s["unit"] == second]
    assert waited["duration_ms"] == 30_000
    assert datetime.fromisoformat(waited["started"]) == START
    assert datetime.fromisoformat(waited["ended"]) == START + timedelta(seconds=30)
    assert waited["change"] == second.partition("/")[0]
    assert first not in {s["unit"] for s in waits}, "a unit that never waited records none"


def test_a_unit_queued_behind_another_ticks_running_build_records_the_slot_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = install(monkeypatch)
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [stored("other/1", "app"), stored("first/1", "app"), stored("second/1", "platform")]
    )
    # Another tick's build: running in the store, its branch lock held (below).
    store.set_state("other/1", RUNNING, branch="spec/other/1")
    build = Build(store, clock, seconds=30)
    monkeypatch.setattr(cli, "build_runner", build)
    monkeypatch.setattr(cli, "resumable_units", lambda *a, **k: [])

    with branch_lock("spec/other/1", root=inst.state_dir / "locks"):
        assert cli.cmd_tick(argparse.Namespace(dry_run=False), inst) == 0

    first, second = build.started
    waits = [s for s in span_lines(inst) if s.get("waited") == "slot"]
    (waited,) = [s for s in waits if s["unit"] == second]
    assert waited["duration_ms"] == 30_000
    assert first not in {s["unit"] for s in waits}
