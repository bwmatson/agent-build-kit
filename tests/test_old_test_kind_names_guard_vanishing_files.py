"""The strict guard reads the working tree, which other tests and tools change while it runs.

A file git tracks but that is gone from the disk when the guard reads it (another test removed
it, a checkout is mid-change) is not read: the guard neither raises nor reports it. This pins
that without waiting on the clock, by deleting the file before the guard runs.
"""

from __future__ import annotations

from pathlib import Path

from tests.factories import commit_files, init_repo
from tests.old_test_kind_names import old_spelling_problems
from tests.tracked_files import guarded_files

# Built in parts so this file carries no old spelling for the guard to find.
OLD_GATE = "ti" + "er2_gate"


def repo_with_a_vanished_file(root: Path) -> Path:
    init_repo(root)
    commit_files(
        root,
        "tracked",
        {"src/kept.py": "x = 1\n", "src/gone.py": f"NAME = '{OLD_GATE}'\n"},
    )
    (root / "src" / "gone.py").unlink()
    return root


def test_a_tracked_file_missing_from_the_disk_is_not_listed(tmp_path: Path) -> None:
    root = repo_with_a_vanished_file(tmp_path)

    found = [p.relative_to(root).as_posix() for p in guarded_files(root, under=["src"])]

    assert found == ["src/kept.py"]


def test_a_generated_track_report_quoting_an_old_unit_id_is_not_scanned(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    commit_files(root, "report", {"docs/reports/20260101-000000-app-health.md": f"- {OLD_GATE}\n"})

    assert old_spelling_problems(root) == []


def test_a_tracked_file_missing_from_the_disk_does_not_fail_the_guard(tmp_path: Path) -> None:
    root = repo_with_a_vanished_file(tmp_path)

    assert old_spelling_problems(root) == []
