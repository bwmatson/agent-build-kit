"""A branch lock records its host; one of another host is held, never reclaimed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_held,
    branch_lock,
    lock_holder_gone,
)
from tests.branch_lock_fakes import dead_pid

BRANCH = "spec/feature/1"


@pytest.fixture(autouse=True)
def on_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")


def written(root: Path, **fields: object) -> Path:
    """The lock file of BRANCH recording `fields`, as a holder that has since died left it."""
    with branch_lock(BRANCH, root=root):
        (path,) = root.glob("*.lock")
        record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, **fields}))
    return path


def test_the_lock_written_carries_the_host(tmp_path: Path) -> None:
    with branch_lock(BRANCH, root=tmp_path):
        (path,) = tmp_path.glob("*.lock")
        assert json.loads(path.read_text())["host"] == "box"


def test_a_lock_of_another_host_with_a_dead_pid_is_busy_and_left(tmp_path: Path) -> None:
    path = written(tmp_path, host="other", pid=dead_pid())
    before = path.read_text()

    with pytest.raises(BranchBusy) as raised, branch_lock(BRANCH, root=tmp_path):
        pass

    assert "other" in str(raised.value)
    assert path.read_text() == before


def test_the_readers_answer_from_the_host_of_the_record(tmp_path: Path) -> None:
    written(tmp_path, host="other", pid=dead_pid())

    assert lock_holder_gone(BRANCH, root=tmp_path) is False
    assert branch_held(BRANCH, root=tmp_path) is True


def test_a_lock_of_this_host_with_a_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    gone = dead_pid()
    path = written(tmp_path, host="box", pid=gone)
    assert lock_holder_gone(BRANCH, root=tmp_path) is True

    with branch_lock(BRANCH, root=tmp_path):
        taken = json.loads(path.read_text())
        assert taken["host"] == "box"
        assert taken["pid"] != gone
