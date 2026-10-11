"""A change whose groups have all started needs no planner: an edit is recorded, not asked about."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED, UnitState
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def started(run: Replan, number: int, state: UnitState) -> None:
    uid = f"feature/{number}"
    run.store.upsert([unit(uid, change="feature", groups=(number,))])
    run.store.set_state(uid, state, branch=f"spec/{uid}")


def edit(run: Replan, text: str) -> None:
    """Record `feature` as planned, then change its tasks.md to `text`."""
    run.record("feature")
    run.write("feature", text)


@pytest.mark.parametrize("state", [FAILED, HELD, IN_REVIEW])
def test_editing_the_text_of_a_started_units_group_makes_no_call_and_records_the_edit(
    state: UnitState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    started(run, 1, state)
    edit(run, tasks_md(1).replace("Group 1", "Group 1, reworded"))
    stale = run.records["feature"]["hash"]

    results = cli.plan_all(run.inst, store=run.store)
    again = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert again["feature"].status == "skipped"
    assert run.records["feature"]["hash"] != stale
    assert (run.records["feature"]["ok"], run.records["feature"]["attempts"]) == (True, 0)
    assert "reworded" in (run.inst.changes_dir / "feature" / "tasks.md").read_text()
    assert run.store.get("feature/1").state == state


def test_editing_the_text_of_a_merged_units_group_is_recorded_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    started(run, 1, MERGED)
    started(run, 2, MERGED)
    edit(run, tasks_md(2).replace("Group 2", "Group 2, reworded"))
    stale = run.records["feature"]["hash"]

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert run.records["feature"]["hash"] != stale
    assert run.records["feature"]["ok"] is True


def test_replan_says_nothing_was_asked_and_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    started(run, 1, FAILED)
    run.record("feature")

    code, out = run.run(capsys, "feature")

    assert code == 0
    assert run.calls == 0
    assert "built by a started unit" in out
    assert run.records["feature"]["ok"] is True


def test_deleting_a_started_group_is_refused_and_asks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    started(run, 1, FAILED)
    started(run, 2, FAILED)
    edit(run, tasks_md(1))
    stale = run.records["feature"]["hash"]

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status in ("refused", "failed")
    assert run.records["feature"]["hash"] == stale
