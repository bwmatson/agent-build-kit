"""The running pass samples its slots each refresh and stamps when a unit became ready
(spec: unit-timeline-is-recorded).

A tick is driven as `test_tick_slot_wait` drives it: two units, one slot, each build
taking thirty seconds of a fake clock, so the pass wakes once per completion.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.fake_clock import FakeClock, install
from tests.otlp import Collector, enabled
from tests.time_limit import LOADED_TEST_TIME_LIMIT

# The tests of this module run whole passes, whose time depends on the machine's load.
pytestmark = [
    pytest.mark.usefixtures("scripted_engine"),
    pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT),
]

SAMPLE_COUNTS = {"running", "in_review", "blocked", "queued", "free_workers", "limit", "cap"}


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


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        yield collector


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


class Pass:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = install(monkeypatch)
        self.inst: Installation = make_installation(
            tmp_path,
            planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
            project_limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit("first/1"), new_unit("second/1")])
        self.build = Build(self.store, self.clock, seconds=30)
        monkeypatch.setattr(cli, "build_runner", self.build)

    @property
    def ledger(self) -> Path:
        return self.inst.state_dir / LEDGER_NAME

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False), self.inst)

    def samples(self) -> list[dict]:
        lines = [json.loads(line) for line in self.ledger.read_text().splitlines() if line]
        return [line for line in lines if line.get("kind") == "sample"]


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pass:
    return Pass(tmp_path, monkeypatch)


# --- ready_at -------------------------------------------------------------------------------
