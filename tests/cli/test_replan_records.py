"""What `abk replan` does to the recorded plans, and what a tick still does."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

ONE = answer(planned("feature/1", (1,)), planned("feature/2", (2,)))


def test_a_change_is_planned_although_its_hash_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.record("feature")
    recorded = run.records["feature"]["hash"]

    code, _ = run.run(capsys, "feature", reply=ONE)

    assert code == 0
    assert run.calls == 1
    assert run.records["feature"] == {"hash": recorded, "attempts": 0, "ok": True}
    assert {u.id for u in run.store.all()} == {"feature/1", "feature/2"}


def test_a_change_that_gave_up_is_planned_by_failed_and_its_attempts_start_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.record("feature", ok=False, attempts=3)

    code, _ = run.run(capsys, "--failed", reply=ONE)

    assert code == 0
    assert run.records["feature"]["attempts"] == 0
    assert run.records["feature"]["ok"] is True


def test_a_replan_that_fails_counts_one_attempt_from_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.record("feature", ok=False, attempts=3)
    run.runtime.ok = False
    run.runtime.error = "the model is unavailable"

    code, _ = run.run(capsys, "--failed")

    assert code == 1
    assert run.records["feature"]["attempts"] == 1


def test_forget_clears_the_records_and_makes_no_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(), other=tasks_md(1))
    run.record("feature")
    run.record("other")

    code, _ = run.run(capsys, "--forget", "feature")

    assert code == 0
    assert run.calls == 0
    assert "feature" not in run.records
    assert "other" in run.records


def test_the_next_tick_plans_a_forgotten_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.record("feature")
    run.run(capsys, "--forget", "feature")
    run.runtime.answer = ONE

    cli.plan_all(run.inst, store=run.store)

    assert run.calls == 1
    assert run.records["feature"]["ok"] is True


def test_a_tick_skips_a_change_a_replan_just_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.run(capsys, "feature", reply=ONE)
    assert run.calls == 1

    cli.plan_all(run.inst, store=run.store)

    assert run.calls == 1


def test_two_writers_of_different_changes_both_land(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch)
    names = [f"change-{n}" for n in range(24)]

    def write(name: str) -> None:
        cli.record_plans(run.inst, {name: {"hash": name, "attempts": 0, "ok": True}})

    threads = [threading.Thread(target=write, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert set(run.records) == set(names)


def test_a_record_set_to_none_is_removed_and_no_temporary_file_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch)
    cli.record_plans(run.inst, {"a": {"hash": "x", "attempts": 0, "ok": True}, "b": {"hash": "y"}})
    before = {p.name for p in run.inst.state_dir.iterdir()}

    cli.record_plans(run.inst, {"a": None})

    path = run.inst.state_dir / "planned.json"
    assert json.loads(path.read_text()) == {"b": {"hash": "y"}}
    assert {p.name for p in run.inst.state_dir.iterdir()} == before
