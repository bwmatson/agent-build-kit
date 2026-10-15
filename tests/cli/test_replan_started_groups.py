"""A change whose groups have all started needs no planner: an edit is recorded, not asked about."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT, change_dir_of
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED, Member, UnitState
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
    assert run.store.get("feature/1").state == state


@pytest.mark.parametrize("state", [FAILED, HELD])
def test_a_requeued_unit_is_not_replanned_and_its_agent_reads_the_edited_tasks_file(
    state: UnitState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    started(run, 1, state)
    edit(run, tasks_md(1).replace("Group 1", "Group 1, reworded"))
    cli.plan_all(run.inst, store=run.store)
    before = run.store.get("feature/1")

    cli.requeue(run.inst, "feature/1", "restart", say=lambda text, error=False: None)
    again = cli.plan_all(run.inst, store=run.store)

    after = run.store.get("feature/1")
    assert run.calls == 0
    assert again["feature"].status == "skipped"
    assert (after.groups, after.repo, after.tier) == (before.groups, before.repo, before.tier)
    # The prompt names the change directory, and the file there is the edited one.
    change_dir = change_dir_of(run.inst.root, "feature")
    assert "{change_dir}" in TESTS_PROMPT
    assert "tasks.md" in TESTS_PROMPT
    assert "reworded" in (Path(change_dir) / "tasks.md").read_text()


def test_a_group_joined_onto_another_changes_planned_unit_leaves_nothing_to_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2), base=tasks_md(1))
    started(run, 1, FAILED)
    run.store.upsert(
        [
            unit(
                "base/1",
                change="base",
                groups=(1,),
                joined=(Member(change="feature", groups=(2,)),),
            )
        ]
    )
    edit(run, tasks_md(2).replace("Group 2", "Group 2, reworded"))

    results = cli.plan_all(run.inst, store=run.store, only={"feature"})

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert run.records["feature"]["ok"] is True


def test_an_edited_priority_reaches_the_planned_unit_that_carries_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2), base=tasks_md(1))
    started(run, 1, FAILED)
    joined = (Member(change="feature", groups=(2,)),)
    run.store.upsert([unit("base/1", change="base", groups=(1,), joined=joined)])
    normal = run.store.get("base/1").priority
    urgent = tasks_md(2).replace("Group 2\n\n", "Group 2\n\nPriority: 1\n\n")
    assert urgent != tasks_md(2)
    edit(run, urgent)

    results = cli.plan_all(run.inst, store=run.store, only={"feature"})

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert run.store.get("base/1").priority < normal


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
    assert "taken by a started unit" in out
    assert run.records["feature"]["ok"] is True


def test_deleting_a_started_group_is_refused_and_asks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    started(run, 1, FAILED)
    started(run, 2, FAILED)
    edit(run, tasks_md(1))
    stale = run.records["feature"]["hash"]
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "refused"
    assert "group(s) 2" in capsys.readouterr().out
    assert run.records["feature"]["hash"] == stale


def test_renumbering_a_started_group_is_refused_and_asks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Group numbers run without gaps, so the unstarted group 2 going away renumbers 3 to 2.
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    started(run, 1, FAILED)
    started(run, 3, FAILED)
    edit(run, tasks_md(2))
    stale = run.records["feature"]["hash"]
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "refused"
    assert "group(s) 3" in capsys.readouterr().out
    assert run.records["feature"]["hash"] == stale


def test_deleting_a_started_group_while_another_is_unstarted_is_refused_and_asks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    started(run, 2, FAILED)
    started(run, 3, FAILED)
    # Group 1, the only unstarted one, is deleted, and the numbers close up.
    edit(run, tasks_md(2))
    stale = run.records["feature"]["hash"]
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "refused"
    assert "group(s) 3" in capsys.readouterr().out
    assert run.records["feature"]["hash"] == stale
