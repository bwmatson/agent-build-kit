"""`touched_tests` lists the tests of a class whatever its name (spec: red-check-by-id): a
`unittest.TestCase` subclass is collected by its base, not its name."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.wiring import touched_tests
from tests.factories import commit_files, init_repo

CASE = (
    "import unittest\n\n\n"
    "class WidgetTests(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n"
)


def test_a_test_in_a_testcase_subclass_not_named_test_is_listed_with_its_class(
    tmp_path: Path,
) -> None:
    work = init_repo(tmp_path / "repo")
    commit_files(work, "base", {"README.md": "base\n"})
    commit_files(work, "test: the case", {"tests/test_a.py": CASE})

    assert touched_tests(work, "HEAD~1", "HEAD") == [("tests/test_a.py", "WidgetTests::test_x")]
