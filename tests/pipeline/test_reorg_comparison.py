"""The before-and-after comparison of a reorganization's test files (standard T26).

Each case builds a small fixture repository, changes its tests the way a reorganization
might, and reads what the comparison reports between the parent and the new version.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.reorg_comparison import Finding, compare_changes, compare_sources
from agent_build_kit.pipeline.shell import git
from tests.factories import commit_files, init_repo

SOURCE = "def thing(x):\n    return x + 1\n"

TWO_TESTS = """\
from pkg.old import thing


def test_a():
    assert thing(1) == 2


def test_b():
    assert thing(2) == 3
"""

ONE_TEST = """\
from pkg.old import thing


def test_a():
    assert thing(1) == 2
"""

MARKED = "import pytest\n\n\n@pytest.mark.timeout(5)\ndef test_a():\n    assert 1\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose first commit holds the source and a test file with two tests."""
    root = init_repo(tmp_path / "app")
    commit_files(root, "start", {"pkg/old.py": SOURCE, "tests/test_x.py": TWO_TESTS})
    return root


def reasons(findings: list[Finding]) -> str:
    return "; ".join(f"{f.standard} {f.path}::{f.test}: {f.reason}" for f in findings)


def test_a_pure_move_with_import_edits_passes(repo: Path) -> None:
    moved = TWO_TESTS.replace("from pkg.old import thing", "from pkg.new import thing as renamed")
    moved = moved.replace("assert thing(", "assert renamed(")
    commit_files(repo, "move", {"pkg/new.py": SOURCE, "tests/test_x.py": moved})

    assert compare_changes(repo, "HEAD~1", "HEAD") == []


def test_a_renamed_marker_name_the_test_asserts_passes() -> None:
    before = (
        "import pytest\n\n\n@pytest.mark.kind_a\ndef test_a():\n"
        "    assert registered_markers() == {'kind_a'}\n"
    )

    assert compare_sources(before, before.replace("kind_a", "kind_b")) == []


def test_a_changed_expected_value_is_reported_by_id(repo: Path) -> None:
    commit_files(repo, "edit", {"tests/test_x.py": TWO_TESTS.replace("== 3", "== 4")})

    found = compare_changes(repo, "HEAD~1", "HEAD")

    assert [(f.standard, f.path, f.test) for f in found] == [
        ("T26", "tests/test_x.py", "test_b")
    ], reasons(found)


def test_a_changed_assertion_is_reported() -> None:
    after = TWO_TESTS.replace("assert thing(1) == 2", "assert thing(1) >= 2")

    found = compare_sources(TWO_TESTS, after)

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_a_deleted_test_is_reported(repo: Path) -> None:
    commit_files(repo, "drop", {"tests/test_x.py": ONE_TEST})

    found = compare_changes(repo, "HEAD~1", "HEAD")

    assert [(f.standard, f.test) for f in found] == [("T26", "test_b")], reasons(found)


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.skip(reason='later')",
        "@pytest.mark.skipif(True, reason='later')",
        "@pytest.mark.xfail",
        "@pytest.mark.slow",
    ],
)
def test_an_added_skip_expected_failure_or_marker_is_reported(decorator: str) -> None:
    after = "import pytest\n" + TWO_TESTS.replace("def test_a", f"{decorator}\ndef test_a")

    found = compare_sources(TWO_TESTS, after)

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_a_raised_time_limit_is_reported() -> None:
    found = compare_sources(MARKED, MARKED.replace("timeout(5)", "timeout(60)"))

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_a_renamed_and_moved_test_file_passes(repo: Path) -> None:
    (repo / "tests/sub").mkdir()
    git(repo, "mv", "tests/test_x.py", "tests/sub/test_y.py")
    git(repo, "commit", "-qm", "move the file")

    assert compare_changes(repo, "HEAD~1", "HEAD") == []


def test_a_merged_pair_of_test_files_passes_when_no_case_body_changed(repo: Path) -> None:
    other = "def test_c():\n    assert 1 + 1 == 2\n"
    commit_files(repo, "second file", {"tests/test_z.py": other})
    git(repo, "rm", "-q", "tests/test_z.py")
    commit_files(repo, "merge", {"tests/test_x.py": TWO_TESTS + "\n\n" + other})

    assert compare_changes(repo, "HEAD~1", "HEAD") == []


def test_a_characterization_test_committed_first_is_the_one_allowed_addition(repo: Path) -> None:
    commit_files(repo, "characterize", {"tests/test_char.py": "def test_c():\n    assert 1\n"})
    commit_files(repo, "move code", {"pkg/new.py": SOURCE})

    assert compare_changes(repo, "HEAD~2", "HEAD") == []


def test_a_test_added_after_the_first_commit_is_reported(repo: Path) -> None:
    commit_files(repo, "move code", {"pkg/new.py": SOURCE})
    commit_files(repo, "late test", {"tests/test_late.py": "def test_c():\n    assert 1\n"})

    found = compare_changes(repo, "HEAD~2", "HEAD")

    assert [f.test for f in found] == ["test_c"], reasons(found)
