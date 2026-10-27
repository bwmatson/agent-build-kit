"""The change-level tracker file: its fields, that it stays out of the plan, and that it travels
with the change (spec: tracker-mapping)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
import yaml

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.tracker_file import (
    FILE_NAME,
    SCHEMA_VERSION,
    Synced,
    TargetMismatch,
    TaskEntry,
    TrackerFile,
    read_for_target,
    read_tracker,
    tracker_path,
    write_tracker,
)
from agent_build_kit.split.select import moved_files, plan_split
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.split_sources import source_installation, write_change

TASKS = (
    "# Tasks\n\nAcceptance: none — a fixture about the tracker file\n\n"
    "## 1. [app] [unit-test] First\n\n- [ ] 1.1 Test: it\n- [ ] 1.2 Do it\n"
)


def tracker(**fields: object) -> TrackerFile:
    base: dict[str, object] = {
        "kind": "board",
        "target": "example-board",
        "feature": Synced(id="100", fields={"title": "Feature"}, revision="7"),
        "tasks": {
            "feature:1.1": TaskEntry(
                id="101", fields={"state": "open"}, revision="3", text_hash="abc123"
            ),
            "feature:1.2": TaskEntry(id="102", text_hash="def456"),
        },
    }
    return TrackerFile.model_validate({**base, **fields})


def change_with(tmp_path: Path) -> Path:
    folder = tmp_path / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text("# feature\n")
    (folder / "tasks.md").write_text(TASKS)
    return folder


def test_the_file_round_trips_with_every_field(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    written = tracker()

    write_tracker(folder, written)

    assert read_tracker(folder) == written
    assert tracker_path(folder) == folder / FILE_NAME
    raw = yaml.safe_load((folder / FILE_NAME).read_text())
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["tasks"]["feature:1.1"]["text_hash"] == "abc123"


def test_the_file_is_written_whole_under_the_lock_with_no_leftover(tmp_path: Path) -> None:
    folder = change_with(tmp_path)

    write_tracker(folder, tracker())
    write_tracker(folder, tracker(target="other-board"))

    assert read_tracker(folder) == tracker(target="other-board")
    assert sorted(p.name for p in folder.iterdir() if p.name != "proposal.md") == [
        "tasks.md",
        FILE_NAME,
    ]


def test_writing_the_file_leaves_the_plan_digest_and_tasks_alone(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    tasks = folder / "tasks.md"
    inst = make_installation(tmp_path)
    digest, text = cli.plan_digest(tasks, inst=inst), tasks.read_text()

    write_tracker(folder, tracker())
    assert cli.plan_digest(tasks, inst=inst) == digest
    write_tracker(folder, tracker(feature=Synced(id="100", revision="8")))

    assert cli.plan_digest(tasks, inst=inst) == digest
    assert tasks.read_text() == text


def test_check_passes_on_a_change_holding_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(TASKS)
    write_tracker(folder, tracker())
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    assert cli.cmd_check(argparse.Namespace(), inst) == 0


def test_an_agent_step_cannot_write_the_file(tmp_path: Path) -> None:
    code, planning = tmp_path / "code", tmp_path / "planning"
    folder = planning / "openspec" / "changes" / "feature"
    for place in (code, folder):
        place.mkdir(parents=True)
    for place in (code, planning):
        subprocess.run(["git", "init", "-q"], cwd=place, check=True)
    payload = {
        "tool_name": "Write",
        "cwd": str(code),
        "tool_input": {"file_path": str(tracker_path(folder))},
    }

    denied = decide(payload, planning_repo=planning, planning_change_dir=folder)

    assert denied is not None
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_archiving_keeps_the_file(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    write_tracker(folder, tracker())
    archive = tmp_path / "openspec" / "changes" / "archive" / "2026-10-26-feature"

    def run(args: list[str], *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess:
        archive.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(archive)
        return subprocess.CompletedProcess(args, 0, "archived\n", "")

    done = archive_ready_changes(
        [stored_unit("feature/1", change="feature", state="merged")],
        planning_repo=tmp_path,
        run=run,
    )

    assert done == ["feature"]
    assert read_tracker(archive) == tracker()


def test_the_split_tools_list_includes_the_file(tmp_path: Path) -> None:
    source = source_installation(tmp_path / "source")
    folder = write_change(source, "feature", ["app"])
    write_tracker(folder, tracker())

    listed = moved_files(source, plan_split(source, "app"))

    assert folder / FILE_NAME in listed


def test_a_file_for_another_target_is_reported_and_its_ids_not_used(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    write_tracker(folder, tracker(target="old-board"))

    with pytest.raises(TargetMismatch, match="feature") as raised:
        read_for_target(folder, "board", "new-board")

    assert "old-board" in str(raised.value)
    assert "new-board" in str(raised.value)


def test_a_file_for_another_kind_is_a_mismatch_too(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    write_tracker(folder, tracker(kind="board"))

    with pytest.raises(TargetMismatch):
        read_for_target(folder, "other-kind", "example-board")


def test_a_file_for_the_configured_target_is_read(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    write_tracker(folder, tracker())

    assert read_for_target(folder, "board", "example-board") == tracker()


def test_with_no_tracker_no_file_is_created_or_read(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    before = sorted(p.name for p in folder.iterdir())

    assert read_tracker(folder) is None
    assert read_for_target(folder, "board", "example-board") is None

    assert sorted(p.name for p in folder.iterdir()) == before
