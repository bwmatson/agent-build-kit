"""A ready unit that waits for a build slot leaves a `span` line in the usage
ledger, from the tick first seeing it ready but for a free slot to the worker
taking the unit's branch lock (spec: unit-time-accounting). Time is a fake clock
the builds advance."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.fake_clock import FakeClock
from tests.time_limit import LOADED_TEST_TIME_LIMIT

# The tests of this module run whole passes, whose time depends on the machine's load.
pytestmark = [
    pytest.mark.usefixtures("scripted_engine"),
    pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT),
]


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
        tier="unit-test",
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
        project_limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
    )
