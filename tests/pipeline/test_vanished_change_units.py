"""The units of a change whose directory is gone are dropped at the planning step, and a
unit waiting on one stops waiting (spec: flake-storm)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UNPLANNED
from agent_build_kit.pipeline.units import PLANNED, RUNNING, blocked
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def vanished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """A planning repo whose `feature` change exists and whose `gone` change has units
    in the store and no directory: `feature/1` waits on `gone/1`, `gone/2` is running."""
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    run.store.upsert(
        [
            unit("gone/1", change="gone", groups=(1,)),
            unit("gone/2", change="gone", groups=(2,)),
            unit("feature/1", change="feature", groups=(1,), depends_on=("gone/1",)),
        ]
    )
    run.store.set_state("gone/2", RUNNING, branch="spec/gone/2")
    run.record("feature")
    return run


def test_an_unstarted_unit_of_a_removed_change_is_unplanned_and_its_waiter_is_freed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = vanished(tmp_path, monkeypatch)
    assert blocked(run.store.get("feature/1"), run.store.all())

    capsys.readouterr()
    cli.plan_all(run.inst, store=run.store)
    out = capsys.readouterr().out

    assert run.store.get("gone/1").state == UNPLANNED
    waiter = run.store.get("feature/1")
    assert waiter.state == PLANNED
    assert not blocked(waiter, run.store.all()), "it no longer waits on a dropped unit"
    assert any("gone/1" in line for line in out.splitlines()), "a message names the unit"


def test_a_running_unit_of_a_removed_change_is_left_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = vanished(tmp_path, monkeypatch)
    before = run.store.get("gone/2")

    cli.plan_all(run.inst, store=run.store)

    assert run.store.get("gone/1").state == UNPLANNED, "the pass ran and dropped the unstarted one"
    assert run.store.get("gone/2") == before


def test_a_restored_change_makes_its_unplanned_unit_planned_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = vanished(tmp_path, monkeypatch)
    cli.plan_all(run.inst, store=run.store)
    assert run.store.get("gone/1").state == UNPLANNED

    run.write("gone", tasks_md(2))
    _, out = run.run(capsys, "gone", reply=answer(planned("gone/1", (1,))))

    assert run.store.get("gone/1").state == PLANNED, out


def test_a_planning_repo_with_no_changes_directory_drops_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = vanished(tmp_path, monkeypatch)
    shutil.rmtree(run.inst.changes_dir)

    cli.plan_all(run.inst, store=run.store)

    assert run.store.get("gone/1").state == PLANNED
