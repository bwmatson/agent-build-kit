"""What a review round's verdict is recorded over: the paths and lines a branch changes
against its base, in a real repository."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_size import branch_diff


def commit(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", name)


def test_the_diff_names_the_changed_paths_and_counts_their_changed_lines(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "keep.txt", "one\n")
    git(tmp_path, "checkout", "-qb", "unit")
    commit(tmp_path, "src/app.py", "a\nb\nc\n")
    commit(tmp_path, "keep.txt", "two\n")

    paths, lines = branch_diff(tmp_path, "main")

    assert sorted(paths) == ["keep.txt", "src/app.py"]
    assert lines == 3 + 1 + 1
