"""The commit-order check: tests exist first, and they failed first.

A unit's branch must read as tests-then-implementation (docs/architecture.md).
That is not a style preference: it is the only
evidence that a test can actually fail, and a test that never failed proves
nothing about the code it supposedly covers.

The structural half is checked here against real git repositories built in
tmp_path, because the rules are about commits and diffs — mocking git would
only test the mock.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.commit_order import (
    STUB_BODY_HINT,
    check_structure,
    classify_paths,
    stub_violations,
)
from tests.factories import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("base\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-q", "-b", "spec/change/1-unit")
    return tmp_path


def commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def test_tests_first_then_implementation_passes(repo: Path) -> None:
    commit(repo, "test: covers the thing", {"tests/test_thing.py": "def test_x(): assert False\n"})
    commit(repo, "feat: the thing", {"src/thing.py": "def x():\n    return 1\n"})

    assert check_structure(repo, "main") == []


def test_implementation_in_the_first_commit_is_rejected(repo: Path) -> None:
    """The failure this whole check exists to catch."""
    commit(
        repo,
        "feat: everything at once",
        {"src/thing.py": "def x():\n    return 1\n", "tests/test_thing.py": "def test_x(): ...\n"},
    )

    problems = check_structure(repo, "main")

    assert problems
    assert "first commit" in problems[0]


def test_a_branch_with_only_tests_is_rejected(repo: Path) -> None:
    """Tests with no implementation behind them is an unfinished unit, not a
    unit that happens to need no code."""
    commit(repo, "test: covers the thing", {"tests/test_thing.py": "def test_x(): ...\n"})

    problems = check_structure(repo, "main")

    assert problems
    assert "implementation" in problems[0]


def test_stubs_are_allowed_in_the_tests_commit(repo: Path) -> None:
    """A test importing a function that doesn't exist yet fails to import
    rather than failing an assertion, so a NotImplementedError stub is allowed
    to make the failure a real one."""
    commit(
        repo,
        "test: covers the thing",
        {
            "tests/test_thing.py": "from src.thing import x\n\ndef test_x(): assert x() == 1\n",
            "src/thing.py": "def x() -> int:\n    raise NotImplementedError\n",
        },
    )
    commit(repo, "feat: the thing", {"src/thing.py": "def x() -> int:\n    return 1\n"})

    assert check_structure(repo, "main") == []


def test_logic_disguised_as_a_stub_is_rejected(repo: Path) -> None:
    """Otherwise 'stubs allowed' becomes a hole big enough to drive the whole
    implementation through."""
    commit(
        repo,
        "test: covers the thing",
        {
            "tests/test_thing.py": "def test_x(): ...\n",
            "src/thing.py": "def x() -> int:\n    return 1\n",
        },
    )
    commit(repo, "feat: more", {"src/other.py": "y = 2\n"})

    problems = check_structure(repo, "main")

    # The headline says which rule broke; a later line names the file and
    # function, so a reviewer gets both the rule and the fix.
    assert "first commit" in problems[0]
    assert any(STUB_BODY_HINT in problem for problem in problems)
    assert any("src/thing.py" in problem for problem in problems)


def test_several_test_implementation_pairs_are_allowed(repo: Path) -> None:
    """A unit can absorb several task groups (§3.4.1.1), so the branch is a
    sequence of pairs rather than exactly one."""
    commit(repo, "test: one", {"tests/test_one.py": "def test_x(): ...\n"})
    commit(repo, "feat: one", {"src/one.py": "x = 1\n"})
    commit(repo, "test: two", {"tests/test_two.py": "def test_y(): ...\n"})
    commit(repo, "feat: two", {"src/two.py": "y = 2\n"})

    assert check_structure(repo, "main") == []


def test_two_test_commits_in_a_row_are_rejected(repo: Path) -> None:
    """Tests, tests, then code is not tests-first for the second batch: the
    second batch was written while the first implementation didn't exist."""
    commit(repo, "test: one", {"tests/test_one.py": "def test_x(): ...\n"})
    commit(repo, "test: two", {"tests/test_two.py": "def test_y(): ...\n"})
    commit(repo, "feat: both", {"src/both.py": "x = 1\n"})

    problems = check_structure(repo, "main")

    assert problems
    assert "in a row" in problems[0]


def test_docs_only_changes_ride_along_with_either_commit(repo: Path) -> None:
    """A README tweak is neither a test nor an implementation, and refusing it
    would push authors into a separate branch for a one-line doc fix."""
    commit(
        repo,
        "test: covers the thing",
        {"tests/test_thing.py": "def test_x(): ...\n", "README.md": "base\nmore\n"},
    )
    commit(repo, "feat: the thing", {"src/thing.py": "x = 1\n"})

    assert check_structure(repo, "main") == []


@pytest.mark.parametrize(
    "path,kind",
    [
        ("tests/test_thing.py", "test"),
        ("svc-a/tests/test_thing.py", "test"),
        ("tests/conftest.py", "test"),
        ("tests/fixtures/page.html", "test"),
        ("src/thing.py", "code"),
        ("README.md", "docs"),
        ("docs/design.md", "docs"),
        ("pyproject.toml", "code"),
    ],
)
def test_paths_are_classified_by_where_they_live(path: str, kind: str) -> None:
    assert classify_paths([path])[path] == kind


def test_stub_detection_reads_python_bodies() -> None:
    stub = "def x() -> int:\n    raise NotImplementedError\n"
    documented_stub = 'def x() -> int:\n    """Docs."""\n    raise NotImplementedError\n'
    declaration = "from dataclasses import dataclass\n\n@dataclass\nclass P:\n    a: int\n"
    logic = "def x() -> int:\n    return 1\n"

    assert stub_violations("s.py", stub) == []
    assert stub_violations("s.py", documented_stub) == []
    assert stub_violations("s.py", declaration) == []
    assert stub_violations("s.py", logic) != []


def test_unparseable_python_is_not_treated_as_a_stub() -> None:
    """A syntax error can't be read, and 'can't tell' must not mean 'allowed'."""
    assert stub_violations("s.py", "def x(:\n") != []
