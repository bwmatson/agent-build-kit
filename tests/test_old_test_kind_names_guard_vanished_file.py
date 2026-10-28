"""The strict guard reads a tracked file that goes missing between listing and reading.

Under parallel load another process can remove a tracked file after git listed it; the guard
treats that file as absent and gives the same answer every time.
"""

from __future__ import annotations

from pathlib import Path

from tests.factories import commit_files, init_repo
from tests.old_test_kind_names import old_spelling_problems

# Built in parts so this file carries no old spelling for the guard to find.
OLD_GATE = "ti" + "er2_gate"


def test_a_tracked_file_removed_after_listing_is_skipped(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(root, "start", {"docs/gone.md": "x\n", "docs/kept.md": OLD_GATE + "\n"})
    (root / "docs" / "gone.md").unlink()

    problems = old_spelling_problems(root)

    assert [p.split(":")[0] for p in problems] == ["docs/kept.md"]


def test_a_repository_whose_only_tracked_file_is_removed_has_no_problem(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(root, "start", {"src/gone.py": "x = 1\n"})
    (root / "src" / "gone.py").unlink()

    assert old_spelling_problems(root) == []
