"""A lease marked committed is a delivery to finish, not chat changes left behind: the tick
delivers the `adopted` event for that commit once and removes the lease, whether or not the
process that made the commit is alive (docs/architecture.md, Editing from chat)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.attach_driver import checked_out, head, leave_lease
from tests.chat_serving import record_session
from tests.conftest import make_installation
from tests.factories import git

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "feature/1"
SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d41"


class Builder:
    """Stands in for `build_runner`: a unit the tick starts ends in review."""

    def run(self, unit, *, base, graph) -> RunOutcome:
        return RunOutcome(status=RunStatus("open"), detail=f"open {unit.id}", pr=7)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="plenty")
    )
    real = cli.build_runner

    def runner(unit, **kwargs):
        # A delivery builds the real runner (it passes `record_merge`); a build is scripted.
        return real(unit, **kwargs) if "record_merge" in kwargs else Builder()

    monkeypatch.setattr(cli, "build_runner", runner)


@pytest.fixture
def usage_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the usage guard itself read or judged: a real read depends on the host's
    credentials, the network and the cache file, so no tick test may reach one."""
    reached: list[str] = []
    real_read, real_judge = usage_guard.current_usage, usage_guard.may_start_unit

    def read(*args, **kwargs):
        reached.append("read")
        return real_read(*args, **kwargs)

    def judge(*args, **kwargs):
        reached.append("judge")
        return real_judge(*args, **kwargs)

    monkeypatch.setattr(usage_guard, "current_usage", read)
    monkeypatch.setattr(usage_guard, "may_start_unit", judge)
    return reached


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_units_in_progress": 50},
    )


def test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease(
    inst: Installation, usage_reads: list[str]
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(
        [
            StoredUnit(
                id=UNIT,
                change="feature",
                title="Build",
                repo="app",
                tier="tier1",
                depends_on=(),
                estimated_lines=140,
                groups=(1,),
            )
        ]
    )
    store.set_state(UNIT, RUNNING, branch="spec/feature/1")
    store.set_state(UNIT, IN_REVIEW, pr=7)
    record_session(inst, UNIT, SESSION, runtime="claude_code")
    tree = checked_out(inst, UNIT)
    (tree / "notes.txt").write_text("a change\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "Add a note")
    leave_lease(lease_dir(inst.state_dir), UNIT, commit=head(tree))

    cli.cmd_tick(argparse.Namespace(dry_run=False), inst)
    cli.cmd_tick(argparse.Namespace(dry_run=False), inst)

    assert Leases(lease_dir(inst.state_dir)).attachment(UNIT) is None
    adopted = [e for e in store.history(UNIT) if e.get("cause") == Cause.ADOPTED.value]
    assert len(adopted) == 1, "the event was delivered once"
    assert usage_reads == [], "the delivery asked the real usage guard, not the scripted one"
