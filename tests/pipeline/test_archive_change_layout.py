"""The archive step finds a change's directory through the one layout function."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import archive
from agent_build_kit.pipeline.archive import archive_ready_changes
from tests.factories import stored_unit


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "archived\n", "")


@pytest.fixture
def relocated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The layout function answering somewhere the old spelling would never look."""
    changes = tmp_path / "elsewhere" / "changes"
    monkeypatch.setattr(archive, "changes_dir_under", lambda root, specs_dir: changes)
    return changes


def merged():
    return stored_unit("add-marker/1", change="add-marker", state="merged")


def test_a_change_is_looked_for_where_the_layout_function_says(
    tmp_path: Path, relocated: Path
) -> None:
    (relocated / "add-marker").mkdir(parents=True)
    runner = Runner()

    archived = archive_ready_changes([merged()], planning_repo=tmp_path, run=runner)

    assert archived == ["add-marker"]


def test_an_archived_change_is_looked_for_beside_the_changes(
    tmp_path: Path, relocated: Path
) -> None:
    (relocated / "archive" / "2026-01-01-add-marker").mkdir(parents=True)
    (relocated / "add-marker").mkdir()
    runner = Runner()

    archived = archive_ready_changes([merged()], planning_repo=tmp_path, run=runner)

    assert archived == []
    assert runner.calls == []
