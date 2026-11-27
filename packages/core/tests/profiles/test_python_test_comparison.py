"""How a Python test file is read into its tests, assertion counts and setup-and-action keys
(spec: toolchain-profiles)."""

from __future__ import annotations

import pytest

from agent_build_kit.profiles.python_test_comparison import read_python_test_file

SAME_SCENARIO = """
def test_one():
    box = build()
    box.run()
    assert box.a == 1


def test_two():
    thing = build()
    thing.run()
    assert thing.b == 2


def test_three():
    other = build()
    other.run()
    assert other.c == 3
"""

ASSERTION_CALLS = """
def test_mock_assertion():
    box = build()
    box.run()
    box.check.assert_called_once_with(1)


def test_unittest_assertion():
    box = build()
    box.run()
    self.assertEqual(box.a, 2)
"""


@pytest.mark.parametrize("text", [SAME_SCENARIO, ASSERTION_CALLS], ids=["assert", "call"])
def test_tests_that_differ_only_in_their_assertions_share_one_key(text: str) -> None:
    read = read_python_test_file(text)
    assert read.readable
    assert {t.assertions for t in read.tests} == {1}
    assert len(read.tests) >= 2
    assert len({t.key for t in read.tests}) == 1


def test_a_test_that_calls_another_function_has_another_key() -> None:
    text = (
        SAME_SCENARIO + "\n\ndef test_four():\n    box = build()\n    box.stop()\n    assert box\n"
    )
    tests = read_python_test_file(text).tests
    assert tests[3].key != tests[0].key
    assert len({t.key for t in tests[:3]}) == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("def test_a():\n    assert 1\n", [("test_a", 1)]),
        (
            "class TestGroup:\n    def test_b(self):\n        assert 1\n"
            "        self.assertEqual(1, 1)\n    def helper(self):\n        pass\n",
            [("TestGroup.test_b", 2)],
        ),
        (
            "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2, 3])\n"
            "def test_c(n):\n    assert n\n",
            [("test_c", 1)],
        ),
    ],
    ids=["module-level", "class", "parametrized"],
)
def test_tests_are_read_with_their_assertion_counts(
    text: str, expected: list[tuple[str, int]]
) -> None:
    assert [(t.name, t.assertions) for t in read_python_test_file(text).tests] == expected


def test_text_that_does_not_parse_is_reported_unreadable_and_not_raised() -> None:
    read = read_python_test_file("def test_x(:\n")
    assert not read.readable
    assert read.tests == ()
