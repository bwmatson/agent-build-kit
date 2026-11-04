"""The wake file: the helper that touches `runs/wake`, and every command that must call it so a
dispatcher starts at once instead of at the next timer."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli.worker import cmd_worker_build
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wake
from agent_build_kit.pipeline.lease import lease_dir
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.attach_driver import checked_out, leave_lease
from tests.conftest import make_installation
from tests.factories import unit
from tests.review_repo import seed_branches
from tests.serving import seed_pipeline, seed_review_round


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning", planning={"worktree_root": str(tmp_path / "worktrees")}
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    seed_pipeline(installation)
    return installation


def aged_wake(inst: Installation) -> Path:
    """The wake file, present and long untouched, so a touch shows."""
    path = inst.state_dir / WAKE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (1, 1))
    return path


def test_touch_creates_the_wake_file_and_its_directory(tmp_path: Path) -> None:
    state_dir = tmp_path / "runs"

    wake.touch(state_dir)

    assert (state_dir / "wake").is_file()


def test_touching_again_moves_the_modification_time_forward(tmp_path: Path) -> None:
    wake.touch(tmp_path)
    os.utime(tmp_path / "wake", (1, 1))

    wake.touch(tmp_path)

    assert (tmp_path / "wake").stat().st_mtime > 1


def test_requeue_touches_the_wake_file(inst: Installation) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", UnitState.FAILED, branch="spec/add-marker/1")
    path = aged_wake(inst)

    assert main(["requeue", "add-marker/1"]) == 0

    assert path.stat().st_mtime > 1


def test_approve_touches_the_wake_file(inst: Installation) -> None:
    seed_branches(inst)
    seed_review_round(inst, "feature/2", 2)
    path = aged_wake(inst)

    assert main(["approve", "feature/2"]) == 0

    assert path.stat().st_mtime > 1


def test_releasing_a_chat_s_lease_touches_the_wake_file(inst: Installation) -> None:
    tree = checked_out(inst, "feature/2")
    (tree / "base.txt").write_text("edited by a chat\n")
    leave_lease(lease_dir(inst.state_dir), "feature/2", files=1)
    path = aged_wake(inst)

    assert main(["attach", "release", "feature/2", "--discard"]) == 0

    assert path.stat().st_mtime > 1


def test_a_worker_s_exit_touches_the_wake_file_through_the_helper(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[Path] = []
    monkeypatch.setattr(wake, "touch", touched.append)

    assert cmd_worker_build(argparse.Namespace(unit="gone/1"), inst) == 0

    assert touched == [inst.state_dir]
