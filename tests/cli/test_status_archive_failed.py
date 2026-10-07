"""`abk status` names a change whose archive failed, and why: the tick carries on
past it, so the status is where a person finds out it was skipped."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import unit


def test_status_lists_a_failed_archive_with_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "merged")
    (inst.changes_dir / "add-marker").mkdir(parents=True)
    (inst.changes_dir / "add-marker" / "tasks.md").write_text("# Tasks\n")

    def failing(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "archive conflicted\nmore detail")

    archived = archive_ready_changes(
        store.all(), planning_repo=inst.root, run=failing, state_dir=inst.state_dir
    )
    assert archived == []

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    output = capsys.readouterr()
    text = output.out + output.err
    assert "archive failed: add-marker — archive conflicted" in text


def test_status_lists_a_withdrawn_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "merged")

    archive_ready_changes(store.all(), planning_repo=inst.root, state_dir=inst.state_dir)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    output = capsys.readouterr()
    assert "archive failed: add-marker — withdrawn" in output.out + output.err
