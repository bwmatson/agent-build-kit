"""The archive writes the tracking copy's files over the repository's, archives, then publishes.

The OpenSpec CLI is the fake runner of `test_archive.py`, made to record what the repository files
held at the moment it was called."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.task_progress import progress_dir
from tests.factories import stored_unit
from tests.pipeline.test_archive import FakeRunner
from tests.progress_support import copy_file, planning, write_copy, write_repository

CHANGE = "add-marker"
UNTICKED = "## 1. [app] [unit-test] Alpha\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n"
TICKED = UNTICKED.replace("[ ]", "[x]")
FOLLOW_UPS = "## From `add-marker/1`\n\n- tidy the helper\n"
REPOSITORY_FOLLOW_UPS = "## From `add-marker/0`\n\n- an older note\n"


class Watching(FakeRunner):
    """Records the change's repository files as they were when `openspec archive` was called."""

    def __init__(self, inst: Installation, *, fails: bool = False) -> None:
        super().__init__(fails=fails)
        self.inst = inst
        self.seen: list[dict[str, str | None]] = []

    def __call__(self, args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        directory = self.inst.changes_dir / CHANGE
        self.seen.append(
            {
                name: path.read_text() if (path := directory / name).exists() else None
                for name in ("tasks.md", "follow-ups.md")
            }
        )
        return super().__call__(args, cwd=cwd, **kwargs)


class Publishing:
    """The publish hook: what it was called with, and what the copy looked like then."""

    def __init__(self, inst: Installation) -> None:
        self.inst = inst
        self.calls: list[str] = []
        self.copy_present: list[bool] = []

    def __call__(self, change: str) -> None:
        self.calls.append(change)
        self.copy_present.append(progress_dir(self.inst, change).exists())


def archive(inst: Installation, runner: FakeRunner, publish: Publishing) -> list[str]:
    return archive_ready_changes(
        [stored_unit(f"{CHANGE}/1", state="merged")],
        planning_repo=inst.root,
        run=runner,
        progress=lambda change: progress_dir(inst, change),
        publish=publish,
    )


def test_the_repository_files_hold_the_copys_ticks_and_blocks_when_openspec_archives(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, UNTICKED)
    write_copy(inst, CHANGE, TICKED)
    copy_file(inst, CHANGE, "follow-ups.md").write_text(FOLLOW_UPS)
    runner = Watching(inst)

    assert archive(inst, runner, Publishing(inst)) == [CHANGE]

    assert runner.seen == [{"tasks.md": TICKED, "follow-ups.md": FOLLOW_UPS}]


def test_a_change_with_no_copy_keeps_its_repository_file_and_gets_no_follow_ups(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, UNTICKED)
    runner = Watching(inst)
    publish = Publishing(inst)

    assert archive(inst, runner, publish) == [CHANGE]

    assert runner.seen == [{"tasks.md": UNTICKED, "follow-ups.md": None}]
    assert publish.calls == [CHANGE]


def test_a_copy_without_follow_ups_leaves_a_repository_follow_ups_file_alone(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, UNTICKED)
    (inst.changes_dir / CHANGE / "follow-ups.md").write_text(REPOSITORY_FOLLOW_UPS)
    write_copy(inst, CHANGE, TICKED)
    runner = Watching(inst)

    archive(inst, runner, Publishing(inst))

    assert runner.seen == [{"tasks.md": TICKED, "follow-ups.md": REPOSITORY_FOLLOW_UPS}]


def test_a_failed_archive_restores_the_repository_files_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, UNTICKED)
    write_copy(inst, CHANGE, TICKED)
    copy_file(inst, CHANGE, "follow-ups.md").write_text(FOLLOW_UPS)
    runner = Watching(inst, fails=True)
    publish = Publishing(inst)

    assert archive(inst, runner, publish) == []

    directory = inst.changes_dir / CHANGE
    assert runner.seen == [{"tasks.md": TICKED, "follow-ups.md": FOLLOW_UPS}]
    assert (directory / "tasks.md").read_text() == UNTICKED
    assert not (directory / "follow-ups.md").exists()
    assert publish.calls == []
    assert copy_file(inst, CHANGE).read_text() == TICKED, "the next tick starts from the same state"


def test_a_success_publishes_once_then_removes_the_copy_and_the_stray_locks(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, UNTICKED)
    write_copy(inst, CHANGE, TICKED)
    copy_file(inst, CHANGE, "follow-ups.md").write_text(FOLLOW_UPS)
    directory = inst.changes_dir / CHANGE
    strays = [directory / "tasks.md.lock", directory / "follow-ups.md.lock"]
    for stray in strays:
        stray.write_text("")
    publish = Publishing(inst)

    assert archive(inst, Watching(inst), publish) == [CHANGE]

    assert publish.calls == [CHANGE]
    assert publish.copy_present == [True], "the copy goes after the hook has run"
    assert not progress_dir(inst, CHANGE).exists()
    assert not any(stray.exists() for stray in strays)
