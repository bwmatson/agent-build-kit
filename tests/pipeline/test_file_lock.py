"""`change_lock`: the lock on one of a change's files, kept outside the repository."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import change_lock, try_file_lock
from tests.conftest import make_installation
from tests.planning_worktree_support import in_repo, installation_at

JOIN = 10


@pytest.fixture(autouse=True)
def data_home(data: Path) -> Path:
    return data


def with_home(tmp_path: Path) -> Installation:
    """An installation whose planning home is `<tmp>/home` (an in-repo one)."""
    setup = in_repo(tmp_path)
    return installation_at(
        setup.worktree, setup.working_copy, planning=dict(home=str(tmp_path / "home"))
    )


def separate(tmp_path: Path) -> Installation:
    """A separate planning repo: no planning home, its state under its own `runs/`."""
    return make_installation(tmp_path / "planning")


def is_held(path: Path) -> bool:
    """Whether another holder has the lock at `path`."""
    with try_file_lock(path) as taken:
        return not taken


def test_a_lock_is_under_the_local_directory_of_the_planning_home(tmp_path: Path) -> None:
    inst = with_home(tmp_path)
    expected = tmp_path / "home" / "local" / "locks" / "changes" / "feature" / "tasks.md.lock"

    with change_lock(inst, "feature", "tasks.md"):
        assert expected.exists()
        assert is_held(expected)

    assert not is_held(expected)


def test_a_separate_planning_repo_keeps_it_under_the_state_directory(tmp_path: Path) -> None:
    inst = separate(tmp_path)
    expected = inst.state_dir / "locks" / "changes" / "feature" / "progress.lock"

    with change_lock(inst, "feature", "progress"):
        assert is_held(expected)

    assert not is_held(expected)


def test_a_lock_is_never_made_beside_the_change(tmp_path: Path) -> None:
    inst = separate(tmp_path)
    (inst.changes_dir / "feature").mkdir(parents=True)

    with change_lock(inst, "feature", "follow-ups.md"):
        pass

    assert list(inst.changes_dir.rglob("*.lock")) == []


def test_two_threads_on_the_same_change_and_name_exclude_each_other(tmp_path: Path) -> None:
    inst = separate(tmp_path)
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def first() -> None:
        with change_lock(inst, "feature", "tasks.md"):
            holding.set()
            release.wait(JOIN)
            order.append("first done")

    def second() -> None:
        with change_lock(inst, "feature", "tasks.md"):
            order.append("second entered")

    one = threading.Thread(target=first)
    one.start()
    assert holding.wait(JOIN)
    two = threading.Thread(target=second)
    two.start()
    release.set()
    one.join(JOIN)
    two.join(JOIN)

    assert order == ["first done", "second entered"]


def test_another_name_of_the_same_change_is_not_held_up(tmp_path: Path) -> None:
    inst = separate(tmp_path)
    done = threading.Event()

    def other() -> None:
        with change_lock(inst, "feature", "progress"):
            done.set()

    with change_lock(inst, "feature", "tasks.md"):
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(JOIN)
        assert done.is_set()


def test_a_different_change_is_not_held_up(tmp_path: Path) -> None:
    inst = separate(tmp_path)
    done = threading.Event()

    def other() -> None:
        with change_lock(inst, "other", "tasks.md"):
            done.set()

    with change_lock(inst, "feature", "tasks.md"):
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(JOIN)
        assert done.is_set()
