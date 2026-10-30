"""`abk tick --dry-run` previews the fix change of each recorded pre-existing failure and
writes nothing (spec: e2e-failures)."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.untouched_failures import preexisting_record, preview
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.untouched_failure_fakes import TEST, failing

ARCHIVED = "tests/far/test_two.py::test_two"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="ok"))
    return make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )


def tree_bytes(inst: Installation) -> dict[str, str]:
    """The planning directory's changes, the record and the unit store, as digests of bytes."""
    files = [*inst.changes_dir.rglob("*"), preexisting_record(inst).path, inst.root / "units.json"]
    return {
        str(path.relative_to(inst.root)): hashlib.sha1(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file()
    }


def open_change(inst: Installation, name: str) -> None:
    folder = inst.changes_dir / name
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text("# Tasks\n")


def archived_change(inst: Installation, name: str) -> None:
    folder = inst.changes_dir / "archive" / f"2026-03-02-{name}"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text("# Tasks\n")


def dry_run(inst: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=True), inst)


def test_a_dry_run_previews_each_recorded_failure_and_writes_nothing(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    UnitStore(inst.root / "units.json").upsert([stored_unit("feature/1", change="feature")])
    record = preexisting_record(inst)
    record.append(failing(TEST))
    record.append(failing(ARCHIVED))
    open_name = fix_change_name(TEST, "fix-test")
    archived_name = fix_change_name(ARCHIVED, "fix-test")
    open_change(inst, open_name)
    archived_change(inst, archived_name)
    runs: list[object] = []
    monkeypatch.setattr(wiring.E2eSession, "run", lambda *args, **kwargs: runs.append(args))
    before = tree_bytes(inst)
    capsys.readouterr()

    assert dry_run(inst) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.endswith(f"exists: {open_name}") for line in lines)
    successor = [line.rsplit("would write: ", 1)[1] for line in lines if "would write: " in line]
    assert len(successor) == 1
    assert successor[0] != archived_name and successor[0].startswith(archived_name)
    assert not any("wrote: " in line.replace("would write: ", "") for line in lines)
    assert tree_bytes(inst) == before, "the planning directory, record and store unchanged"
    assert not (inst.changes_dir / successor[0]).exists()
    assert runs == [], "no base run"


def test_a_dry_run_with_nothing_pending_still_previews_and_says_what_the_ensure_step_says(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    preexisting_record(inst).append(failing(TEST))
    before = tree_bytes(inst)
    capsys.readouterr()

    assert dry_run(inst) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1, "an idle tick says nothing else"
    assert tree_bytes(inst) == before
    assert lines[0].endswith(preview(inst, TEST).line), "the line the preview gives"
