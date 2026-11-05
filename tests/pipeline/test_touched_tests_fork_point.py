"""The tests a unit adds or changes are listed from the point its branch left its base, not from
the base's tip (spec: unit-own-tests): a base that has moved on adds no test to the unit."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.wiring import own_test_ids, touched_in, touched_tests
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_scope_fakes import CHANGED, NEW, OLD
from tests.factories import commit_files, git, init_repo

NOT_THE_FORK = "not the point the branch left it"
UNIT_OWN = [
    ("tests/live/test_new.py", "test_new"),
    ("tests/live/test_old.py", "test_old"),
]


def moved_on(tmp_path: Path) -> Path:
    """A unit that left `main` at A, adding one test and changing another; `main` has since moved
    to B, changing a test the unit's checkout also has and adding one the unit does not have.
    The unit's branch is checked out."""
    repo = init_repo(tmp_path / "repo")
    commit_files(repo, "A", {"tests/live/test_old.py": OLD, "tests/live/test_shared.py": OLD})
    git(repo, "switch", "-q", "-c", "unit")
    commit_files(repo, "unit", {"tests/live/test_new.py": NEW, "tests/live/test_old.py": CHANGED})
    git(repo, "switch", "-q", "main")
    commit_files(repo, "B", {"tests/live/test_shared.py": CHANGED, "tests/live/test_trunk.py": NEW})
    git(repo, "switch", "-q", "unit")
    return repo


def test_a_test_the_trunk_changed_and_the_checkout_also_has_is_not_listed(tmp_path: Path) -> None:
    repo = moved_on(tmp_path)

    assert touched_tests(repo, "main") == UNIT_OWN


def test_the_tests_a_unit_adds_and_changes_are_listed_through_the_file_listing_too(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)

    assert touched_in(repo, "main", [PROFILE]) == UNIT_OWN
    assert own_test_ids(repo, "main", [(repo, PROFILE, [])]) == [
        "tests/live/test_new.py::test_new",
        "tests/live/test_old.py::test_old",
    ]


def test_uncommitted_work_in_the_checkout_is_still_the_units(tmp_path: Path) -> None:
    repo = moved_on(tmp_path)
    (repo / "tests/live/test_draft.py").write_text("def test_draft():\n    assert True\n")

    assert touched_tests(repo, "main") == [
        *UNIT_OWN,
        ("tests/live/test_draft.py", "test_draft"),
    ]


def test_the_listing_for_a_commit_and_its_parent_is_unchanged(tmp_path: Path) -> None:
    repo = moved_on(tmp_path)

    assert touched_tests(repo, "unit~1", "unit") == UNIT_OWN
    assert touched_tests(repo, "main~1", "main") == [
        ("tests/live/test_shared.py", "test_old"),
        ("tests/live/test_trunk.py", "test_new"),
    ]


def test_a_unit_at_its_base_lists_nothing_however_far_the_trunk_has_moved(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_files(repo, "A", {"tests/live/test_old.py": OLD})
    git(repo, "switch", "-q", "-c", "unit")
    git(repo, "switch", "-q", "main")
    commit_files(repo, "B", {"tests/live/test_old.py": CHANGED, "tests/live/test_trunk.py": NEW})
    git(repo, "switch", "-q", "unit")

    assert touched_tests(repo, "main") == []
    assert touched_in(repo, "main", [PROFILE]) == []


def test_a_stacked_unit_whose_parent_gained_a_commit_lists_only_its_own(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_files(repo, "A", {"tests/live/test_old.py": OLD})
    git(repo, "switch", "-q", "-c", "parent")
    commit_files(repo, "parent 1", {"tests/live/test_parent.py": NEW})
    git(repo, "switch", "-q", "-c", "unit")
    commit_files(repo, "unit", {"tests/live/test_new.py": NEW})
    git(repo, "switch", "-q", "parent")
    commit_files(repo, "parent 2", {"tests/live/test_parent_later.py": NEW})
    git(repo, "switch", "-q", "unit")

    assert touched_tests(repo, "parent") == [("tests/live/test_new.py", "test_new")]


def test_a_ref_git_cannot_resolve_is_listed_against_itself_and_the_log_says_so(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)
    said: list[str] = []

    with pytest.raises(subprocess.CalledProcessError):
        touched_tests(repo, "no-such-ref", log=said.append)

    [line] = said
    assert "no-such-ref" in line and NOT_THE_FORK in line


def test_a_ref_with_no_common_history_is_listed_against_itself_and_the_log_says_so(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)
    git(repo, "switch", "-q", "--orphan", "other")
    commit_files(repo, "other", {"tests/live/test_other.py": NEW})
    git(repo, "switch", "-q", "unit")
    said: list[str] = []

    listed = touched_in(repo, "other", [PROFILE], log=said.append)

    # Against `other` itself: every test the checkout has that `other` lacks.
    assert ("tests/live/test_new.py", "test_new") in listed
    assert ("tests/live/test_shared.py", "test_old") in listed
    [line] = said
    assert "other" in line and NOT_THE_FORK in line


def test_a_ref_that_resolves_says_nothing(tmp_path: Path) -> None:
    repo = moved_on(tmp_path)
    said: list[str] = []

    touched_in(repo, "main", [PROFILE], log=said.append)

    assert said == []
