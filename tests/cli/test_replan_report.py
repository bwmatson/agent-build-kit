"""`abk replan --report` shows each change's plan state, its started and unstarted units and
whether a replan would call the planner, with no model call and no write (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import MERGED, PLANNED, RUNNING, UnitState
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import stored_unit
from tests.split_sources import snapshot_tree

pytestmark = pytest.mark.usefixtures("scripted_engine")


def put(run: Replan, uid: str, groups: tuple[int, ...], state: UnitState = PLANNED) -> None:
    run.store.upsert([stored_unit(uid, change=uid.split("/")[0], groups=groups)])
    if state != PLANNED:
        run.store.set_state(uid, state, branch=f"spec/{uid}", pr=1)


def partly_started(run: Replan) -> None:
    """`feature`: one merged, one running and two planned units, one group each."""
    put(run, "feature/1", (1,), MERGED)
    put(run, "feature/2", (2,), RUNNING)
    put(run, "feature/3", (3,))
    put(run, "feature/4", (4,))
    run.record("feature")


def section(out: str, change: str) -> str:
    """The lines the report gives `change`: from the line naming it to the next change's."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{change}:"))
    rest = lines[start + 1 :]
    end = next((i for i, line in enumerate(rest) if line and not line.startswith(" ")), len(rest))
    return "\n".join([lines[start], *rest[:end]])


def test_a_partly_started_change_is_reported_with_its_counts_and_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    partly_started(run)

    code, out = run.run(capsys, "feature", "--report")

    report = section(out, "feature")
    assert code == 0
    assert "2 started" in report and "2 unstarted" in report
    for uid, group in (("feature/1", 1), ("feature/2", 2), ("feature/3", 3), ("feature/4", 4)):
        assert f"{uid}: group {group}" in report
    assert "would call the planner once" in report
    assert "total: 1 planner call" in out
    assert run.calls == 0


def test_a_change_whose_every_group_is_taken_asks_nothing_of_the_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, taken=tasks_md(2))
    put(run, "taken/1", (1, 2), MERGED)
    run.record("taken")

    code, out = run.run(capsys, "taken", "--report")

    assert code == 0
    assert "would ask nothing of the planner" in section(out, "taken")
    assert "total: 0 planner calls" in out


def test_the_total_adds_the_changes_and_all_lists_every_active_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4), taken=tasks_md(1), fresh=tasks_md(1))
    partly_started(run)
    put(run, "taken/1", (1,), MERGED)
    run.record("taken")

    code, out = run.run(capsys, "--all", "--report")

    assert code == 0
    for change in ("feature", "taken", "fresh"):
        assert section(out, change)
    assert "would call the planner once" in section(out, "fresh")
    assert "total: 2 planner calls" in out
    assert run.calls == 0


def test_a_report_writes_nothing_and_calls_no_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4), fresh=tasks_md(1))
    partly_started(run)
    (run.inst.state_dir / "notes.txt").write_text("kept\n")
    before = snapshot_tree(run.inst.root)

    code, _ = run.run(capsys, "--all", "--report")

    assert code == 0
    assert snapshot_tree(run.inst.root) == before
    assert run.calls == 0


def test_a_name_that_is_not_a_change_is_refused_as_replan_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))

    code, out = run.run(capsys, "nowhere", "--report")

    assert code == 1
    assert "abk replan: 'nowhere' is not a change (changes: feature)" in out
    assert run.calls == 0


def test_a_change_with_a_tag_problem_is_refused_and_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, broken=tasks_md(1).replace("[app]", "[nowhere]"))

    code, out = run.run(capsys, "broken", "--report")

    assert code == 1
    assert "task-group problem" in out and "run `abk tags`" in out
    assert "would call the planner" not in out
    assert "total: 0 planner calls" in out
    assert run.calls == 0


def test_a_started_unit_whose_group_left_tasks_md_is_refused_and_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    put(run, "feature/1", (1, 2), MERGED)
    run.record("feature")

    code, out = run.run(capsys, "feature", "--report")

    assert code == 0
    assert "would be refused, no planner call: group(s) 2 are built by a started unit" in out
    assert "total: 0 planner calls" in out
    assert run.calls == 0
