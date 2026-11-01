"""Mirroring archived changes onto a board: closed, done, capped per run, and listed on a dry
run (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.trackers.backfill import backfill
from tests.trackers.board_support import CHANGE, REPO_URL, board_section, covering, write_change
from tests.trackers.reconciler_support import RecordingTracker
from tests.trackers.test_reconciler import groups_tasks

DONE_TASKS = groups_tasks(2).replace("- [ ]", "- [x]")
THREE = ["change", "group", "task"]


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


class Archive:
    """Archived changes on disk and a recording tracker for the repo."""

    def __init__(self, tmp_path: Path, levels: list[str], names: list[str]) -> None:
        self.tracker = RecordingTracker()
        section = board_section(levels)
        trackers.register(section.kind, lambda _section: self.tracker)
        self.changes_dir = tmp_path / "changes"
        self.changes_dir.mkdir()
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        self.names = names
        self.archive_dir = self.changes_dir / "archive"
        self.archive_dir.mkdir()
        for name in names:
            write_change(self.archive_dir, f"2026-10-01-{name}", tasks=DONE_TASKS)

    def folder(self, name: str) -> Path:
        return self.archive_dir / f"2026-10-01-{name}"

    def units(self):  # noqa: ANN201
        return [
            covering(f"{name}/1", (1, 2), UnitState.MERGED).model_copy(update={"change": name})
            for name in self.names
        ]

    def run(self, cap: int, *, dry_run: bool = False, names: list[str] | None = None):  # noqa: ANN201
        return backfill(
            "app",
            changes_dir=self.changes_dir,
            changes=names if names is not None else self.names,
            units=self.units(),
            repo_url=REPO_URL,
            state_dir=self.state_dir,
            cap=cap,
            dry_run=dry_run,
        )


def test_an_archived_change_is_mirrored_as_closed_and_done_items(tmp_path: Path) -> None:
    archive = Archive(tmp_path, THREE, [CHANGE])

    report = archive.run(cap=50)

    change = archive.tracker.find_by_marker(CHANGE)
    assert change is not None
    assert (change.kit_state or change.state) == "done"
    for marker in (f"{CHANGE}:1", f"{CHANGE}:2", f"{CHANGE}:1.1", f"{CHANGE}:2.2"):
        item = archive.tracker.find_by_marker(marker)
        assert item is not None, marker
        assert (item.kit_state or item.state) == "done", marker
    assert report.created == 7
    assert (archive.folder(CHANGE) / "tracker.yaml").is_file()
    assert not (archive.changes_dir / CHANGE).exists()


def test_the_change_item_links_to_the_archived_folder(tmp_path: Path) -> None:
    archive = Archive(tmp_path, ["change", "group"], [CHANGE])

    archive.run(cap=50)

    change = archive.tracker.find_by_marker(CHANGE)
    assert change is not None
    assert f"/changes/archive/2026-10-01-{CHANGE}" in change.body


def test_without_a_task_level_no_task_items_are_made(tmp_path: Path) -> None:
    archive = Archive(tmp_path, ["change", "group"], [CHANGE])

    report = archive.run(cap=50)

    assert report.created == 3
    assert archive.tracker.find_by_marker(f"{CHANGE}:1.1") is None


def test_a_cap_of_ten_over_thirty_items_makes_ten_per_run_over_three_runs(
    tmp_path: Path,
) -> None:
    # Ten changes of one change item and two group items each: thirty items.
    names = [f"change-{number}" for number in range(10)]
    archive = Archive(tmp_path, ["change", "group"], names)

    made = [archive.run(cap=10).created for _ in range(4)]

    assert made == [10, 10, 10, 0]
    assert len(archive.tracker.made("create")) == 30


def test_a_dry_run_lists_the_creates_and_the_tracker_sees_no_write(tmp_path: Path) -> None:
    archive = Archive(tmp_path, ["change", "group"], [CHANGE])

    report = archive.run(cap=50, dry_run=True)

    assert report.created == 0
    assert list(report.listed) == [CHANGE, f"{CHANGE}:1", f"{CHANGE}:2"]
    assert not archive.tracker.writes()
    assert not list(archive.state_dir.iterdir())
    assert not (archive.folder(CHANGE) / "tracker.yaml").exists()
