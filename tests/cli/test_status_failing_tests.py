"""`abk status` names a fix change whose units all finished while a unit still fails the test
(spec: untouched-failure-fixes)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit

TEST = "tests/test_widget.py::test_renders_the_label"
FIX = "fix-test-tests-test-widget-py-test-renders-the-label"
OTHER_TEST = "tests/test_widget.py::test_sizes_the_label"
OTHER_FIX = "fix-test-tests-test-widget-py-test-sizes-the-label"


def status_with_fixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fixes: dict[str, tuple[str, UnitState]],
) -> list[str]:
    """`abk status` over fix changes (name to the test it fixes and its one unit's state), and a
    unit `one/1` whose last run failed each of those tests."""
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one")])
    for name, (test, state) in fixes.items():
        (workspace.changes_dir / name).mkdir(parents=True)
        store.upsert([stored_unit(f"{name}/1", change=name)])
        store.set_state(f"{name}/1", state)
        flake_record(workspace).append(
            Flake(
                test=test,
                unit="one/1",
                command="uv run pytest -n auto -q",
                output=f"FAILED {test}",
                at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
                change=name,
                failing=True,
            )
        )
    return run_status(workspace, monkeypatch, capsys)


@pytest.mark.parametrize(
    "state", [UnitState.SATISFIED, UnitState.MERGED, UnitState.CLOSED, UnitState.RETIRED]
)
def test_status_names_a_finished_fix_change_whose_test_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
) -> None:
    lines = status_with_fixes(tmp_path, monkeypatch, capsys, {FIX: (TEST, state)})

    named = [line for line in lines if FIX in line and "one/1" in line and TEST in line]
    assert len(named) >= 1, "\n".join(lines)
    assert any("finished" in line for line in named), "the line says the fix finished"


def test_status_names_no_finished_fix_for_a_change_still_being_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_with_fixes(
        tmp_path,
        monkeypatch,
        capsys,
        {FIX: (TEST, UnitState.SATISFIED), OTHER_FIX: (OTHER_TEST, UnitState.RUNNING)},
    )

    assert any("finished" in line and FIX in line for line in lines), "\n".join(lines)
    assert not any(OTHER_FIX in line and "finished" in line for line in lines), "\n".join(lines)
