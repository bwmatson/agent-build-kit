"""The before-and-after comparison of a reorganization's test files (standard T26).

Each case builds a small fixture repository, changes its tests the way a reorganization
might, and reads what the comparison reports between the parent and the new version. The
cases that need no history compare two versions of one file.
"""

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.reorg_comparison import Finding, compare_changes, compare_sources
from agent_build_kit.pipeline.shell import git
from agent_build_kit.profiles.base import ComparesTests, ToolchainProfile
from tests.factories import commit_files, init_repo

PYTHON = profiles.get("python-uv")
NODE = profiles.get("node-npm")

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

TWO_FUNCTIONS = """\
from pkg import a, b


def test_a():
    assert a(1) == 2
"""

CONSTANT = "EXPECTED = 2\n\n\ndef test_a():\n    assert f() == EXPECTED\n"

FIXTURE = """\
import pytest


@pytest.fixture
def value():
    return 2


def test_a(value):
    assert value == 2
"""

TWO_MARKERS = """\
import pytest


@pytest.mark.p
def test_1():
    assert 1


@pytest.mark.q
def test_2():
    assert 2
"""

CLASSED = """\
class TestA:
    def test_x(self):
        assert 1
"""


def for_path(path: str) -> ToolchainProfile:
    """The profile of a file by its suffix, as a repository with a project of each would."""
    return PYTHON if path.endswith(".py") else NODE


def changes(repo: Path, base: str = "HEAD~1", head: str = "HEAD") -> list[Finding]:
    return compare_changes(repo, base, head, toolchain_for=for_path)


def sources(before: str, after: str) -> list[Finding]:
    assert isinstance(PYTHON, ComparesTests)
    return compare_sources(PYTHON, before, after)


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

    assert changes(repo) == []


def test_a_renamed_marker_name_the_test_asserts_passes() -> None:
    before = (
        "import pytest\n\n\n@pytest.mark.kind_a\ndef test_a():\n"
        "    assert registered_markers() == {'kind_a'}\n"
    )

    assert sources(before, before.replace("kind_a", "kind_b")) == []


def test_reordering_tests_with_different_markers_passes() -> None:
    swapped = (
        "import pytest\n\n\n@pytest.mark.q\ndef test_2():\n    assert 2\n\n\n"
        "@pytest.mark.p\ndef test_1():\n    assert 1\n"
    )

    assert sources(TWO_MARKERS, swapped) == []


def test_a_changed_expected_value_is_reported_by_id(repo: Path) -> None:
    commit_files(repo, "edit", {"tests/test_x.py": TWO_TESTS.replace("== 3", "== 4")})

    found = changes(repo)

    assert [(f.standard, f.path, f.test) for f in found] == [
        ("T26", "tests/test_x.py", "test_b")
    ], reasons(found)


def test_a_changed_assertion_is_reported() -> None:
    after = TWO_TESTS.replace("assert thing(1) == 2", "assert thing(1) >= 2")

    found = sources(TWO_TESTS, after)

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_another_imported_function_in_the_same_place_is_reported() -> None:
    found = sources(TWO_FUNCTIONS, TWO_FUNCTIONS.replace("assert a(1)", "assert b(1)"))

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_a_renamed_local_variable_passes() -> None:
    before = "def test_a():\n    got = compute()\n    assert got == 2\n"

    assert sources(before, before.replace("got", "result")) == []


@pytest.mark.parametrize(
    ("before", "after", "name"),
    [
        (CONSTANT, CONSTANT.replace("EXPECTED = 2", "EXPECTED = 3"), "EXPECTED"),
        (FIXTURE, FIXTURE.replace("return 2", "return 3"), "value"),
    ],
    ids=["constant", "fixture"],
)
def test_a_changed_constant_or_fixture_is_reported_by_name(
    before: str, after: str, name: str
) -> None:
    found = sources(before, after)

    assert [f.test for f in found] == [name], reasons(found)


def test_a_deleted_test_is_reported(repo: Path) -> None:
    commit_files(repo, "drop", {"tests/test_x.py": ONE_TEST})

    found = changes(repo)

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

    found = sources(TWO_TESTS, after)

    assert [f.test for f in found] == ["test_a"], reasons(found)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (TWO_TESTS, "import pytest\npytestmark = pytest.mark.skip\n" + TWO_TESTS),
        (CLASSED, "import pytest\n\n\n@pytest.mark.skip\n" + CLASSED),
        (
            CLASSED,
            CLASSED.replace(
                "    def test_x", "    pytestmark = pytest.mark.xfail\n\n    def test_x"
            ),
        ),
    ],
    ids=["module", "class decorator", "class attribute"],
)
def test_a_skip_added_to_a_module_or_class_is_reported_for_each_test(
    before: str, after: str
) -> None:
    found = sources(before, after)

    assert found != [], "nothing reported"
    assert {f.test for f in found} <= {"test_a", "test_b", "TestA.test_x"}, reasons(found)


def test_a_raised_time_limit_is_reported() -> None:
    found = sources(MARKED, MARKED.replace("timeout(5)", "timeout(60)"))

    assert [f.test for f in found] == ["test_a"], reasons(found)


def test_a_renamed_and_moved_test_file_passes(repo: Path) -> None:
    (repo / "tests/sub").mkdir()
    git(repo, "mv", "tests/test_x.py", "tests/sub/test_y.py")
    git(repo, "commit", "-qm", "move the file")

    assert changes(repo) == []


def test_a_test_file_with_an_unusual_path_is_compared(repo: Path) -> None:
    commit_files(repo, "unusual", {"tests/tést_ü.py": TWO_TESTS})
    commit_files(repo, "edit", {"tests/tést_ü.py": TWO_TESTS.replace("== 3", "== 4")})

    found = changes(repo)

    assert [(f.path, f.test) for f in found] == [("tests/tést_ü.py", "test_b")], reasons(found)


def test_a_merged_pair_of_test_files_passes_when_no_case_body_changed(repo: Path) -> None:
    other = "def test_c():\n    assert 1 + 1 == 2\n"
    commit_files(repo, "second file", {"tests/test_z.py": other})
    git(repo, "rm", "-q", "tests/test_z.py")
    commit_files(repo, "merge", {"tests/test_x.py": TWO_TESTS + "\n\n" + other})

    assert changes(repo) == []


def test_a_merged_pair_of_test_files_reports_a_case_body_that_changed(repo: Path) -> None:
    other = "def test_c():\n    assert 1 + 1 == 2\n"
    commit_files(repo, "second file", {"tests/test_z.py": other})
    git(repo, "rm", "-q", "tests/test_z.py")
    commit_files(
        repo, "merge", {"tests/test_x.py": TWO_TESTS + "\n\n" + other.replace("== 2", "== 3")}
    )

    found = changes(repo)

    assert [f.test for f in found] == ["test_c"], reasons(found)


def test_a_node_shaped_test_file_is_left_to_a_profile_that_cannot_compare(repo: Path) -> None:
    assert not isinstance(NODE, ComparesTests)
    commit_files(
        repo, "node test", {"src/foo.test.ts": "test('a', () => { expect(f()).toBe(2) })\n"}
    )
    commit_files(repo, "edit", {"src/foo.test.ts": "test('a', () => { expect(f()).toBe(3) })\n"})

    assert changes(repo) == []


def test_a_characterization_test_committed_first_is_the_one_allowed_addition(repo: Path) -> None:
    commit_files(repo, "characterize", {"tests/test_char.py": "def test_c():\n    assert 1\n"})
    commit_files(repo, "move code", {"pkg/new.py": SOURCE})

    assert changes(repo, "HEAD~2") == []


def test_a_characterization_test_added_to_an_existing_file_is_allowed(repo: Path) -> None:
    commit_files(
        repo, "characterize", {"tests/test_x.py": TWO_TESTS + "\n\ndef test_c():\n    assert 1\n"}
    )
    commit_files(repo, "move code", {"pkg/new.py": SOURCE})

    assert changes(repo, "HEAD~2") == []


def test_a_characterization_test_a_later_commit_changes_is_reported(repo: Path) -> None:
    commit_files(repo, "characterize", {"tests/test_char.py": "def test_c():\n    assert 1\n"})
    commit_files(repo, "edit it", {"tests/test_char.py": "def test_c():\n    assert 2\n"})

    found = changes(repo, "HEAD~2")

    assert [f.test for f in found] == ["test_c"], reasons(found)


def test_a_test_added_after_the_first_commit_is_reported(repo: Path) -> None:
    commit_files(repo, "move code", {"pkg/new.py": SOURCE})
    commit_files(repo, "late test", {"tests/test_late.py": "def test_c():\n    assert 1\n"})

    found = changes(repo, "HEAD~2")

    assert [f.test for f in found] == ["test_c"], reasons(found)
