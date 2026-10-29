"""`abk init` decides a path is a git checkout by its working-tree root, like the track runner."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.detect import detect_repo


def test_a_folder_with_a_git_entry_that_is_not_a_repository_is_not_git(tmp_path: Path) -> None:
    path = tmp_path / "app"
    (path / ".git").mkdir(parents=True)

    assert not detect_repo(path).is_git
