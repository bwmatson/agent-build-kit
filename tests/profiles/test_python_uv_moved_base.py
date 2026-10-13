"""What the python-uv profile will not select for (spec:
a-moved-base-is-checked-by-what-it-can-affect).

A moved base asks the profile about the unit's files together with the files the move brought
in. A file the profile cannot place in a test's reach makes it answer nothing, even when
seed data is there to select by, so that the full suite runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.profiles.test_python_uv_affected_tests import ask, plain_repo, seeded, workspace_repo

UNPLACED = ["uv.lock", "pyproject.toml", "tests/conftest.py", "tests/helpers.py"]


@pytest.mark.parametrize("path", UNPLACED)
def test_a_changed_file_it_cannot_place_gives_nothing(tmp_path: Path, path: str) -> None:
    repo = plain_repo(tmp_path)

    assert ask(repo, [path], [], seeded(tmp_path)) is None


@pytest.mark.parametrize("path", UNPLACED)
def test_one_file_it_cannot_place_among_placed_ones_gives_nothing(
    tmp_path: Path, path: str
) -> None:
    repo = plain_repo(tmp_path)

    assert ask(repo, ["src/x.py", path], [], seeded(tmp_path)) is None


def test_a_shared_test_helper_inside_a_member_gives_nothing(tmp_path: Path) -> None:
    repo = workspace_repo(tmp_path)

    assert ask(repo, ["svc-a/tests/conftest.py"], [], seeded(tmp_path)) is None
