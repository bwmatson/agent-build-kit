"""What a replan does to the units the store holds, and what it prints about it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UNPLANNED
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
    branch_name,
)
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

STARTED = (RUNNING, IN_REVIEW, FAILED, HELD, MERGED, SATISFIED)


def seed(run: Replan, uid: str, state: UnitState = PLANNED, **fields) -> None:
    number = int(uid.split("/")[1])
    run.store.upsert([unit(uid, change="feature", groups=(number,), **fields)])
    if state != PLANNED:
        run.store.set_state(uid, state, branch=f"spec/{uid}")


def test_started_and_finished_units_keep_state_and_branch_and_are_reported_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    last = len(STARTED) + 1
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(last))
    for number, state in enumerate(STARTED, start=1):
        seed(run, f"feature/{number}", state)
    seed(run, f"feature/{last}")
    run.record("feature")
    before = {u.id: u for u in run.store.all()}
    # The planner is told which units have started and plans only the rest.
    reply = answer(planned(f"feature/{last}", (last,), lines=300))

    code, out = run.run(capsys, "feature", reply=reply)

    assert code == 0, out
    for number, state in enumerate(STARTED, start=1):
        uid = f"feature/{number}"
        after = run.store.get(uid)
        assert (after.state, after.branch) == (state, f"spec/{uid}")
        assert after.estimated_lines == before[uid].estimated_lines
        assert f"kept: {uid}, {state.value}" in out
    assert run.store.get(f"feature/{last}").estimated_lines == 300


def test_a_planned_unit_takes_the_new_shape_and_it_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    seed(run, "feature/1")
    seed(run, "feature/2")
    run.record("feature")
    reply = answer(planned("feature/1", (1,), lines=250), planned("feature/2", (2,)))

    _, out = run.run(capsys, "feature", reply=reply)

    assert run.store.get("feature/1").estimated_lines == 250
    assert any("feature/1" in ln and "250" in ln for ln in out.splitlines())


def test_an_unstarted_unit_the_plan_drops_becomes_unplanned_and_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    seed(run, "feature/1")
    seed(run, "feature/9")
    run.record("feature")

    _, out = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))

    assert run.store.get("feature/9").state == UNPLANNED
    assert any("feature/9" in ln and "unplanned" in ln for ln in out.splitlines())


def test_a_join_dropped_because_a_unit_started_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), other=tasks_md(2))
    seed(run, "feature/1")
    run.record("feature")
    join = {"onto": "feature/1", "change": "other", "groups": [1], "estimated_lines": 40}

    # The unit is unstarted when the plan is checked and held by a live build
    # when the join is written: its branch is locked.
    with branch_lock(branch_name(run.store.get("feature/1")), root=run.inst.state_dir / "locks"):
        _, out = run.run(capsys, "other", reply=answer(planned("other/2", (2,)), joins=[join]))

    assert "join" in out
    assert "dropped" in out
    assert run.store.get("feature/1").estimated_lines == 140


def test_a_stale_dependency_is_removed_and_a_needs_dependency_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        base=tasks_md(2),
        feature=tasks_md(2, needs={2: "base group 2"}),
    )
    run.store.upsert(
        [
            unit("base/1", change="base", groups=(1,)),
            unit("base/2", change="base", groups=(2,)),
            unit("feature/1", change="feature", groups=(1,)),
            unit("feature/2", change="feature", groups=(2,), depends_on=("base/1", "feature/1")),
        ]
    )
    run.record("feature")
    run.record("base")
    reply = answer(
        planned("feature/1", (1,)), planned("feature/2", (2,), depends_on=("feature/1",))
    )

    code, out = run.run(capsys, "feature", reply=reply)

    assert code == 0
    assert run.store.get("feature/2").depends_on == ("feature/1", "base/2")
    assert "feature/2: no longer depends on base/1" in out


def test_nothing_is_printed_for_an_unchanged_unit_and_the_run_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    run.store.upsert([unit("feature/1", change="feature", groups=(1,), estimated_lines=80)])
    run.record("feature")

    code, out = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))

    assert code == 0
    assert "nothing changed" in out.lower()
    assert "depends" not in out
    assert "kept" not in out
