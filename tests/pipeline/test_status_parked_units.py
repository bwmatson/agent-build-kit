"""`abk status` lists a unit parked for its worktree with the reason, so a person
knows which tree to clean before requeueing it."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD
from tests.conftest import make_installation
from tests.factories import stored_unit

REASON = "uncommitted changes in the worktree: stray.txt — commit or remove them by hand"


def test_status_lists_a_unit_parked_for_its_worktree_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one"), stored_unit("two/1", change="two")])
    store.set_state("one/1", HELD, note=REASON, cause=Cause.DIRTY_WORKTREE)
    store.set_state("two/1", HELD, note="needs a human", cause=Cause.NEEDS_HUMAN)
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    parked = next(line for line in lines if "one/1" in line)
    assert "stray.txt" in parked
    assert "commit or remove" in parked
    assert not any("two/1" in line for line in lines), "other holds are not listed here"
