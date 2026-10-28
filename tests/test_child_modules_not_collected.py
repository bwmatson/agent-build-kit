"""The child pytest sources under `tests/child_modules/` are not tests of this repository."""

from __future__ import annotations

from tests.child_pytest import collect_listing
from tests.tracked_files import ROOT, guarded_files

FOLDER = "tests/child_modules"
SIBLING = "tests/test_child_modules_not_collected.py"


def scenario_files() -> list[str]:
    return [
        path.relative_to(ROOT).as_posix()
        for path in guarded_files(root=ROOT, under=[FOLDER], suffixes={".py"})
    ]


def test_the_repos_own_collection_lists_nothing_of_the_folder() -> None:
    result = collect_listing(FOLDER, SIBLING)
    output = result.output

    assert any(name.endswith("/conftest.py") for name in scenario_files()), scenario_files()
    assert result.code == 0, output
    assert [line for line in output.splitlines() if "child_modules/" in line] == []


def test_no_file_of_the_folder_is_named_like_a_test() -> None:
    files = scenario_files()

    assert files, "tests/child_modules/ holds no Python file"
    assert [name for name in files if name.rsplit("/", 1)[-1].startswith("test_")] == []
