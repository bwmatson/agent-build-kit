"""The guard against the old e2e marker name (spec: test-markers, "The old name does not return").

The old name in any tracked file but the changelog fails the guard naming the file; the changelog
may hold it; the repository passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.factories import commit_files, init_repo
from tests.old_marker_name import old_marker_problems
from tests.time_limit import LOADED_TEST_TIME_LIMIT

REPOSITORY = Path(__file__).resolve().parents[1]
# Built in parts so this file carries no old name for the guard to find.
OLD = "local" + "_stack"


@pytest.mark.parametrize(
    "path",
    ["src/agent_build_kit/step.py", "tests/fixtures/case.py", "docs/guide.md", "pyproject.toml"],
)
def test_a_file_holding_the_old_name_fails_naming_the_file(tmp_path: Path, path: str) -> None:
    root = init_repo(tmp_path)
    commit_files(root, "old", {path: "x = 1\nMARKER = '" + OLD + "'\n"})

    problems = old_marker_problems(root)

    assert len(problems) == 1
    assert f"{path}:2" in problems[0]


def test_the_changelog_may_hold_the_old_name(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    commit_files(root, "log", {"CHANGELOG.md": "## Unreleased\n\n- Renamed `" + OLD + "`.\n"})

    assert old_marker_problems(root) == []


def test_the_changelog_holding_it_passes_beside_clean_files(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    commit_files(
        root,
        "mixed",
        {"CHANGELOG.md": "- `" + OLD + "`\n", "src/step.py": "MARKER = 'e2e'\n"},
    )

    assert old_marker_problems(root) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_the_repository_does_not_hold_the_old_marker_name() -> None:
    assert old_marker_problems(REPOSITORY) == []
