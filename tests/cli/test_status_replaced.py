"""The replan report and `abk status` show a replaced unit with its successor (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit, unit


def seed(run: Replan, uid: str, group: int) -> None:
    run.store.upsert([unit(uid, change="feature", groups=(group,))])


@pytest.mark.usefixtures("scripted_engine")
def test_a_replan_reports_each_replaced_unit_with_its_successor_and_a_dropped_one_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    seed(run, "feature/1", 1)
    seed(run, "feature/2", 2)
    seed(run, "feature/9", 9)
    run.record("feature")

    _, out = run.run(capsys, "feature", reply=answer(planned("feature/3", (1, 2))))

    lines = out.splitlines()
    assert "feature/1: now unplanned, replaced by feature/3" in lines
    assert "feature/2: now unplanned, replaced by feature/3" in lines
    assert "feature/9: now unplanned, the plan no longer has it" in lines


@pytest.mark.parametrize("state", [UnitState.PLANNED, UnitState.RUNNING])
def test_status_prints_one_replaced_line_until_the_edge_is_repointed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.import_units(
        [
            stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
            stored_unit("x/5", change="x"),
            stored_unit("d/1", change="d", depends_on=("x/3",), state=state, branch="spec/d/1"),
            stored_unit("e/1", change="e", depends_on=("x/3",)),
        ]
    )

    before = run_status(inst, monkeypatch, capsys)
    store.set_dependencies("d/1", ("x/5",))
    store.set_dependencies("e/1", ("x/5",))
    after = run_status(inst, monkeypatch, capsys)

    [shown] = [line for line in before if "replaced:" in line]
    assert shown.endswith("  replaced: x/3 by x/5")
    assert [line for line in after if "replaced:" in line] == []
