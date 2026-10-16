"""The unit of a scheduled change a tick wrote is tracked like any other: listed by `abk status`,
counted against `max_units_in_progress`, waiting for the tier 2 lock, and started only when the
usage guard admits a unit (spec: tier2-schedule).

The change comes from a tick's own write step; the planner is a stand-in that turns each
scheduled change into one tier 2 unit, as the real one turns the group of its `tasks.md`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.tier2_schedule import is_scheduled, scheduled_name
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, SATISFIED
from agent_build_kit.pipeline.usage_guard import Decision
from tests.factories import stored_unit
from tests.tick_pass import Builder, isolate, tick
from tests.tier2_lock_fakes import Foreign, install_clock, tier2_runner
from tests.tier2_schedule_fakes import AT, TODAY, on_today, planning, scheduled_changes

pytestmark = pytest.mark.usefixtures("scripted_engine")

HOUR = 3600
NAME = scheduled_name("app", TODAY)
UNIT = f"{NAME}/1"


def installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **limits: int
) -> tuple[Installation, UnitStore, Builder]:
    """`app`, due, and `platform`, scheduled `off`; `app` has a tier 2 unit that has merged.
    The builder ends the scheduled unit satisfied, as a passing run does."""
    inst = planning(tmp_path, {"app": None, "platform": "off"}, project_limits=limits)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("app-work/1", change="app-work", repo="app", tier="tier2")])
    store.set_state("app-work/1", MERGED, pr=1)
    builder = Builder(store)
    builder.scripts[UNIT] = lambda: RunStatus.SATISFIED
    builder.ends[UNIT] = (SATISFIED, None, "scheduled tier 2 passed")
    monkeypatch.setattr(cli, "build_runner", builder)
    return inst, store, builder


def plan_scheduled(inst: Installation, *, store: UnitStore, **kwargs: object) -> None:
    """The planner for a scheduled change: one tier 2 unit of its repo, once."""
    known = {unit.change for unit in store.all()}
    for name in scheduled_changes(inst):
        if is_scheduled(name) and name not in known:
            store.upsert([stored_unit(f"{name}/1", change=name, repo="app", tier="tier2")])


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


def test_the_limit_counts_the_scheduled_unit_and_holds_it_until_a_place_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, builder = installation(tmp_path, monkeypatch, max_units_in_progress=1)
    in_review(store, "other/1")

    assert tick(inst) == 0
    assert builder.started == [], "at the limit it does not start"
    assert store.get(UNIT).state == PLANNED

    store.set_state("other/1", MERGED, pr=9)
    assert tick(inst) == 0

    assert builder.started == [UNIT]
    assert store.get(UNIT).state == SATISFIED


def test_a_started_scheduled_unit_takes_a_place_from_the_next_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, builder = installation(tmp_path, monkeypatch, max_units_in_progress=1)
    # The builder's default outcome leaves the unit open (in review): a state that counts.
    del builder.scripts[UNIT], builder.ends[UNIT]

    assert tick(inst) == 0
    store.upsert([stored_unit("late/1", change="late", repo="app")])
    assert tick(inst) == 0

    assert store.get(UNIT).state == IN_REVIEW
    assert store.get("late/1").state == PLANNED, "the scheduled unit holds the one place"


def test_a_scheduled_unit_waits_for_a_held_tier_2_lock_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, _ = installation(tmp_path, monkeypatch)
    assert tick(inst) == 0
    clock = install_clock(monkeypatch, AT)
    other = Foreign(inst.state_dir / "tier2.lock")
    clock.release_at(2 * HOUR, other.release)
    log: list[str] = []
    runner, ran = tier2_runner(inst, store, monkeypatch, log, store.get(UNIT))
    tree = tmp_path / "tree"
    tree.mkdir()

    ok, _ = runner.run_tier2(cwd=tree)

    assert ok and ran.record_seen is not None, "it ran when the lock was free"
    assert clock.elapsed() >= 2 * HOUR
    assert any("tier 2 is busy" in line for line in log)


def test_a_usage_refusal_delays_the_scheduled_unit_until_the_guard_admits_a_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, builder = installation(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )

    assert tick(inst) == 0
    assert tick(inst) == 0

    assert scheduled_changes(inst) == [NAME], "written once, not twice"
    assert builder.started == []
    assert [unit.id for unit in store.all() if is_scheduled(unit.change)] == []

    monkeypatch.setattr(cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="ok"))
    assert tick(inst) == 0

    assert builder.started == [UNIT]
    assert scheduled_changes(inst) == [NAME]
