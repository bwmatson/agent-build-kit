"""The unit of a scheduled change a tick wrote is tracked like any other: listed by `abk status`,
counted against `max_units_in_progress`, waiting for the e2e-test lock, and started only when the
usage guard admits a unit (spec: e2e-schedule).

The change comes from a tick's own write step; the planner is a stand-in that turns each
scheduled change into one e2e-test unit, as the real one turns the group of its `tasks.md`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_schedule import is_scheduled, scheduled_name
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, SATISFIED
from tests.e2e_lock_fakes import Foreign, e2e_runner, install_clock
from tests.e2e_schedule_fakes import AT, TODAY, on_today, planning, scheduled_changes
from tests.factories import stored_unit
from tests.tick_pass import Builder, isolate, tick

pytestmark = pytest.mark.usefixtures("scripted_engine")

HOUR = 3600
NAME = scheduled_name("app", TODAY)
UNIT = f"{NAME}/1"


def installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **limits: int
) -> tuple[Installation, UnitStore, Builder]:
    """`app`, due, and `platform`, scheduled `off`; `app` has an e2e-test unit that has merged.
    The builder ends the scheduled unit satisfied, as a passing run does."""
    inst = planning(tmp_path, {"app": None, "platform": "off"}, project_limits=limits)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("app-work/1", change="app-work", repo="app", tier="e2e-test")])
    store.set_state("app-work/1", MERGED, pr=1)
    builder = Builder(store)
    builder.scripts[UNIT] = lambda: RunStatus.SATISFIED
    builder.ends[UNIT] = (SATISFIED, None, "scheduled e2e-test passed")
    monkeypatch.setattr(cli, "build_runner", builder)
    return inst, store, builder


def plan_scheduled(inst: Installation, *, store: UnitStore, **kwargs: object) -> None:
    """The planner for a scheduled change: one e2e-test unit of its repo, once."""
    known = {unit.change for unit in store.all()}
    for name in scheduled_changes(inst):
        if is_scheduled(name) and name not in known:
            store.upsert([stored_unit(f"{name}/1", change=name, repo="app", tier="e2e-test")])


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    on_today(monkeypatch)
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "plan_all", plan_scheduled)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)


def in_review(store: UnitStore, uid: str) -> None:
    store.upsert([stored_unit(uid, change=uid.split("/")[0], repo="app")])
    store.set_state(uid, IN_REVIEW, pr=9, branch=f"spec/{uid}")


def test_the_scheduled_unit_is_listed_by_status_with_its_change_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store, _ = installation(tmp_path, monkeypatch, max_units_in_progress=1)
    in_review(store, "other/1")

    assert tick(inst) == 0
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    listed = [line for line in capsys.readouterr().out.splitlines() if UNIT in line]
    assert len(listed) == 1
    assert NAME in listed[0] and PLANNED in listed[0]


def test_a_scheduled_unit_waits_for_a_held_e2e_lock_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, _ = installation(tmp_path, monkeypatch)
    assert tick(inst) == 0
    clock = install_clock(monkeypatch, AT)
    other = Foreign(inst.state_dir / "e2e.lock")
    clock.release_at(2 * HOUR, other.release)
    log: list[str] = []
    runner, ran = e2e_runner(inst, store, monkeypatch, log, store.get(UNIT))
    tree = tmp_path / "tree"
    tree.mkdir()

    ok, _ = runner.run_e2e(cwd=tree)

    assert ok and ran.record_seen is not None, "it ran when the lock was free"
    assert clock.elapsed() >= 2 * HOUR
    assert any("e2e-test is busy" in line for line in log)
