"""`abk status` names a merged unit whose branch is kept, with the reason stored for it (spec:
merged-branch-cleanup)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from tests.conftest import make_installation, run_status
from tests.factories import new_unit

UNIT = "add-marker/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path, planning={"state_dir": "."})


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit(UNIT)])
    store.set_state(UNIT, MERGED, pr=4, branch=f"spec/{UNIT}")
    return store


@pytest.mark.parametrize(
    "reason",
    [
        "worktree has uncommitted changes",
        "spec/other/2 is building on it",
        "the host refused to delete it: branch deletion is forbidden",
    ],
)
def test_a_merged_unit_whose_branch_is_kept_is_listed_with_its_reason(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    store.set_branch_kept(UNIT, reason)

    lines = run_status(inst, monkeypatch, capsys)

    assert any(UNIT in line and reason in line for line in lines)


def test_a_merged_unit_whose_branches_are_both_gone_is_not_listed(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.set_branch_kept(UNIT, "worktree has uncommitted changes")
    store.set_branch_kept(UNIT, "")

    lines = run_status(inst, monkeypatch, capsys)

    assert not any("uncommitted changes" in line for line in lines)
    assert not any("kept" in line and UNIT in line for line in lines)
