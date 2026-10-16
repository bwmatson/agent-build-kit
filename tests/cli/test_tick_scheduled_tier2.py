"""A tick writes the scheduled tier 2 change of a due repo before planning and ahead of the usage
guard, is not idle while one is due, and `--dry-run` says what it would write and what exists
(spec: tier2-schedule)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2_schedule import scheduled_name
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.pipeline.usage_guard import Decision
from tests.factories import stored_unit
from tests.tier2_schedule_fakes import TODAY, on_today, open_change, planning, scheduled_changes

pytestmark = pytest.mark.usefixtures("scripted_engine")


class Calls:
    """What a tick asked of the planner and of the usage window."""

    def __init__(self) -> None:
        self.plans = 0
        self.usage_reads = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    on_today(monkeypatch)
    seen = Calls()

    def plan(inst: Installation, **kwargs: object) -> None:
        seen.plans += 1

    def usage() -> None:
        seen.usage_reads += 1

    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", plan)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    monkeypatch.setattr(cli, "current_usage", usage)
    monkeypatch.setattr(cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="ok"))
    return seen


def installation(tmp_path: Path, schedule: str | None = None) -> tuple[Installation, UnitStore]:
    """One repo, `app`, with a tier 2 unit that has merged, so only the schedule is work."""
    inst = planning(tmp_path, {"app": schedule})
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("app-work/1", change="app-work", repo="app", tier="tier2")])
    store.set_state("app-work/1", MERGED, pr=1)
    return inst, store


def tick(inst: Installation, *, dry_run: bool = False) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=dry_run, only=None), inst)


def planning_directory(inst: Installation, store: UnitStore) -> tuple[dict[str, bytes], list]:
    """The changes with their bytes, and the units with their states: what a dry run leaves."""
    files = {
        str(path.relative_to(inst.root)): path.read_bytes()
        for path in sorted(inst.changes_dir.rglob("*"))
        if path.is_file()
    }
    return files, [(unit.id, unit.state) for unit in store.all()]


# --- the dry run ---------------------------------------------------------------------


def test_a_dry_run_says_it_would_write_the_change_of_a_due_repo_and_writes_nothing(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path)
    before = planning_directory(inst, store)
    capsys.readouterr()

    assert tick(inst, dry_run=True) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.endswith(f"would write: {scheduled_name('app', TODAY)}") for line in lines)
    assert not any("exists: " in line for line in lines)
    assert planning_directory(inst, store) == before
    assert scheduled_changes(inst) == []


def test_a_dry_run_says_the_open_change_exists_and_writes_nothing(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path)
    name = open_change(inst, "app", TODAY)
    before = planning_directory(inst, store)
    capsys.readouterr()

    assert tick(inst, dry_run=True) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.endswith(f"exists: {name}") for line in lines)
    assert not any("would write: " in line for line in lines)
    assert planning_directory(inst, store) == before


# --- a tick ----------------------------------------------------------------------------


def test_a_tick_with_nothing_else_to_do_and_a_due_repo_is_not_idle_and_writes_the_change(
    tmp_path: Path, calls: Calls
) -> None:
    inst, store = installation(tmp_path)
    assert cli.has_work(inst, store), "a due repo is work"

    assert tick(inst) == 0

    assert scheduled_changes(inst) == [scheduled_name("app", TODAY)]
    assert calls.plans >= 1, "the change is planned in the round that wrote it"


def test_a_tick_with_nothing_due_returns_idle_without_reading_usage(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = installation(tmp_path)
    assert tick(inst) == 0
    (name,) = scheduled_changes(inst)
    (inst.changes_dir / "archive").mkdir()
    (inst.changes_dir / name).rename(inst.changes_dir / "archive" / f"{TODAY}-{name}")
    monkeypatch.setattr(cli, "current_usage", lambda: pytest.fail("read the usage window"))
    plans = calls.plans

    assert not cli.has_work(inst, store)
    assert tick(inst) == 0

    assert calls.plans == plans
    assert scheduled_changes(inst) == []


def test_the_change_is_written_before_planning(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, _ = installation(tmp_path)
    seen: list[list[str]] = []
    monkeypatch.setattr(
        cli, "plan_all", lambda inst, **kwargs: seen.append(scheduled_changes(inst))
    )

    assert tick(inst) == 0

    assert seen and seen[0] == [scheduled_name("app", TODAY)]


def test_a_usage_refusal_still_writes_the_change_but_does_not_plan_it_or_write_a_second(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, _ = installation(tmp_path)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )

    assert tick(inst) == 0
    assert tick(inst) == 0

    assert scheduled_changes(inst) == [scheduled_name("app", TODAY)]
    assert calls.plans == 0, "planning is a model call, behind the guard"


def test_a_tick_writes_one_change_for_each_due_split_of_a_repo(
    tmp_path: Path, calls: Calls
) -> None:
    splits = {"app": {"claude_code": {"marker": "runtime_claude_code"}}}
    inst = planning(tmp_path, repo_splits=splits)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("app-work/1", change="app-work", repo="app", tier="tier2")])
    store.set_state("app-work/1", MERGED, pr=1)

    assert tick(inst) == 0

    assert scheduled_changes(inst) == sorted(
        scheduled_name("app", TODAY, split) for split in ("claude_code", "rest")
    )
