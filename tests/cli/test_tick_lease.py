"""A tick leaves a unit alone while someone holds its lease, and resumes it once released.

`cmd_tick` is driven with a builder that records which units it was asked to build, as
the scheduling tests do.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.chat_serving import record_session
from tests.conftest import make_installation

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


class Builder:
    """Stands in for `build_runner`: records what it was asked to build, and ends it in review."""

    def __init__(self, store: UnitStore) -> None:
        self.store = store
        self.started: list[str] = []

    def __call__(self, unit, **kwargs) -> Builder._Run:
        return Builder._Run(self)

    class _Run:
        def __init__(self, builder: Builder) -> None:
            self.builder = builder

        def run(self, unit, *, base, graph) -> RunOutcome:
            self.builder.started.append(unit.id)
            self.builder.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
            self.builder.store.set_state(unit.id, IN_REVIEW, pr=7)
            return RunOutcome(status=RunStatus("open"), detail=f"open {unit.id}", pr=7)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    fake = Builder(UnitStore(tmp_path / "units.json"))
    monkeypatch.setattr(cli, "build_runner", fake)
    return fake


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_units_in_progress": 50},
    )


def stored(uid: str, **overrides) -> StoredUnit:
    change, _, _ = uid.partition("/")
    fields: dict = {
        "id": uid,
        "change": change,
        "title": f"Build {uid}",
        "repo": "app",
        "tier": "tier1",
        "depends_on": (),
        "estimated_lines": 140,
        "groups": (1,),
    }
    return StoredUnit(**{**fields, **overrides})


def tick(inst: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=False), inst)


def test_a_tick_starts_no_step_on_a_unit_whose_lease_is_held(
    builder: Builder, inst: Installation
) -> None:
    builder.store.upsert([stored("feature/1"), stored("other/1", repo="platform")])
    assert Leases(lease_dir(inst.state_dir)).take("feature/1", "tab:a")

    assert tick(inst) == 0

    assert builder.started == ["other/1"], "the leased unit waits, its neighbour does not"
    assert builder.store.get("feature/1").state == PLANNED


def test_a_tick_does_not_rework_a_leased_unit_a_poll_sent_back(
    builder: Builder, inst: Installation
) -> None:
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    builder.store.set_state("feature/1", IN_REVIEW, pr=7)
    builder.store.set_state(
        "feature/1", PLANNED, note="rework requested: merge conflict", cause=Cause.REWORK
    )
    Leases(lease_dir(inst.state_dir)).take("feature/1", "tab:a")

    tick(inst)

    assert builder.started == []


def test_releasing_the_lease_returns_the_unit_to_the_next_tick(
    builder: Builder, inst: Installation
) -> None:
    builder.store.upsert([stored("feature/1")])
    leases = Leases(lease_dir(inst.state_dir))
    leases.take("feature/1", "tab:a")
    tick(inst)
    assert builder.started == []

    leases.release("feature/1", "tab:a")
    tick(inst)

    assert builder.started == ["feature/1"]
    assert builder.store.get("feature/1").state == IN_REVIEW


def test_a_lease_left_by_a_process_that_has_exited_does_not_hold_the_unit(
    builder: Builder, inst: Installation
) -> None:
    builder.store.upsert([stored("feature/1")])
    code = (
        "import sys; from pathlib import Path; "
        "from agent_build_kit.pipeline.lease import Leases; "
        "assert Leases(Path(sys.argv[1])).take('feature/1', 'tab:gone')"
    )
    subprocess.run([sys.executable, "-c", code, str(lease_dir(inst.state_dir))], check=True)

    tick(inst)

    assert builder.started == ["feature/1"]


def test_a_tick_does_not_resume_a_leased_unit_an_event_positioned(
    builder: Builder, inst: Installation
) -> None:
    """A unit in review with its thread, sent back by an event: the tick resumes it from its
    recorded node, unless someone is chatting with it."""
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    record_session(inst, "feature/1", "sess", runtime="claude_code")
    leases = Leases(lease_dir(inst.state_dir))
    leases.take("feature/1", "tab:a")

    tick(inst)
    assert builder.started == []

    leases.release("feature/1", "tab:a")
    tick(inst)

    assert builder.started == ["feature/1"]


def test_a_lease_taken_after_the_pass_picked_the_unit_stops_its_build_under_the_branch_lock(
    builder: Builder, inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass has judged the unit ready; before its build takes the branch lock, a tab takes
    the lease. The build re-reads under the lock, sees the lease and does not run."""
    builder.store.upsert([stored("feature/1")])
    picked = cli.ready_units

    def ready_then_leased(*args, **kwargs):
        ready = picked(*args, **kwargs)
        Leases(lease_dir(inst.state_dir)).take("feature/1", "tab:a")
        return ready

    monkeypatch.setattr(cli, "ready_units", ready_then_leased)

    tick(inst)

    assert builder.started == []
    assert builder.store.get("feature/1").state == PLANNED
