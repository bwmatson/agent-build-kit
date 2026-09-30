"""Which tests a commit range defined, deleted or edited inside, read from a
real repository's history.

A diff carries context: with the default three lines either side of an edit, a
neighbouring test appears in it untouched. What the range did is which lines it
added or removed and which test each falls within, so these tests build real
commits and ask through the public name.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.wiring import defined_tests_in_range
from tests.factories import git, init_repo

BEFORE = """import pytest


def test_above():
    assert True


def test_edited():
    x = 1
    y = 2
    assert x == y - 1


def test_below():
    assert True


class TestGroup:
    def test_beside(self):
        assert True

    def test_in_class(self):
        a = 1
        assert a


@pytest.mark.parametrize("n", [1, 2])
def test_decorated(n):
    assert n


def test_far():
    a = 1
    b = 2
    c = 3
    d = 4
    assert a


def test_removed():
    assert True
"""


def _range(tmp_path: Path, files: dict[str, tuple[str, str]]) -> tuple[Path, str, str]:
    """A repo with `before` of each file at the base and `after` at the head."""
    repo = init_repo(tmp_path / "r")
    for name, (before, _) in files.items():
        (repo / name).write_text(before)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    for name, (_, after) in files.items():
        (repo / name).write_text(after)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit")
    return repo, base, git(repo, "rev-parse", "HEAD").strip()


def test_a_test_on_a_context_line_is_not_counted_and_the_edited_one_is(tmp_path: Path) -> None:
    after = BEFORE.replace("    assert x == y - 1\n", "    assert x == y - 1\n    assert x\n")
    repo, base, head = _range(tmp_path, {"test_mod.py": (BEFORE, after)})

    # The one-line edit sits within three lines of the test below it, so that
    # test is in the diff's text as context.
    diff = git(repo, "diff", base, head)
    assert "def test_below" in diff

    assert defined_tests_in_range(repo, base, head) == ["test_edited"]


def test_a_definition_added_and_one_deleted_are_both_counted(tmp_path: Path) -> None:
    after = BEFORE.replace("def test_removed():\n    assert True\n", "")
    after += "\n\ndef test_added():\n    assert True\n"
    repo, base, head = _range(tmp_path, {"test_mod.py": (BEFORE, after)})

    assert defined_tests_in_range(repo, base, head) == ["test_added", "test_removed"]


def test_an_edit_to_a_decorator_or_a_method_counts_for_that_test(tmp_path: Path) -> None:
    after = BEFORE.replace("[1, 2]", "[1, 2, 3]").replace(
        "        a = 1\n        assert a", "        assert 1"
    )
    repo, base, head = _range(tmp_path, {"test_mod.py": (BEFORE, after)})

    assert defined_tests_in_range(repo, base, head) == ["test_decorated", "test_in_class"]


def test_a_range_that_touches_no_test_counts_none(tmp_path: Path) -> None:
    source = "def helper():\n    return 1\n\n\ndef test_kept():\n    assert helper()\n"
    repo, base, head = _range(
        tmp_path,
        {"test_mod.py": (source, source), "helpers.py": ("X = 1\n", "X = 2\n")},
    )
    assert defined_tests_in_range(repo, base, head) == []

    # An edit to the helper a test calls is not an edit inside the test.
    (repo / "test_mod.py").write_text(source.replace("return 1", "return 2"))
    git(repo, "commit", "-qam", "edit the helper")
    later = git(repo, "rev-parse", "HEAD").strip()
    assert defined_tests_in_range(repo, head, later) == []


def test_each_file_of_a_range_is_read_against_its_own_lines(tmp_path: Path) -> None:
    other = "def test_other():\n    assert 1\n\n\ndef test_untouched():\n    assert 1\n"
    after = BEFORE.replace("    assert x == y - 1\n", "    assert x\n")
    repo, base, head = _range(
        tmp_path,
        {
            "test_mod.py": (BEFORE, after),
            "test_more.py": (other, other.replace("assert 1\n\n\ndef", "assert 2\n\n\ndef", 1)),
        },
    )

    assert defined_tests_in_range(repo, base, head) == ["test_edited", "test_other"]
