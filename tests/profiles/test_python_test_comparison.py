"""How the Python profile reads the shape of a test file (spec: toolchain-profiles)."""

from __future__ import annotations

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import ReadsTestShape


def python_profile() -> ReadsTestShape:
    profile = profiles.get("python-uv")
    assert isinstance(profile, ReadsTestShape)
    return profile


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


def test_tests_that_differ_only_in_their_assertions_share_one_key() -> None:
    read = python_profile().read_test_file("tests/test_box.py", SAME_SCENARIO)
    assert read.readable
    assert [t.name for t in read.tests] == ["test_one", "test_two", "test_three"]
    assert [t.assertions for t in read.tests] == [1, 1, 1]
    assert len({t.key for t in read.tests}) == 1


def test_a_test_that_calls_another_function_has_another_key() -> None:
    text = (
        SAME_SCENARIO + "\n\ndef test_four():\n    box = build()\n    box.stop()\n    assert box\n"
    )
    tests = python_profile().read_test_file("tests/test_box.py", text).tests
    assert tests[3].key != tests[0].key
    assert len({t.key for t in tests[:3]}) == 1


def test_module_level_and_class_tests_are_read_and_a_parametrized_test_is_one() -> None:
    text = (
        "import pytest\n\n\n"
        "@pytest.mark.parametrize('n', [1, 2, 3])\n"
        "def test_a(n):\n    assert n\n\n\n"
        "class TestGroup:\n"
        "    def test_b(self):\n        assert 1\n        self.assertEqual(1, 1)\n"
        "    def helper(self):\n        pass\n"
    )
    tests = python_profile().read_test_file("tests/test_g.py", text).tests
    assert [(t.name, t.assertions) for t in tests] == [("test_a", 1), ("TestGroup.test_b", 2)]


def test_text_that_does_not_parse_is_reported_unreadable_and_not_raised() -> None:
    read = python_profile().read_test_file("tests/test_x.py", "def test_x(:\n")
    assert not read.readable
    assert read.tests == ()


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("tests/test_store.py", "store"),
        ("tests/store_test.py", "store"),
        ("tests/conftest.py", None),
        ("tests/helpers.py", None),
        ("src/app/store.py", None),
    ],
)
def test_a_test_file_is_named_for_a_module_or_for_none(path: str, module: str | None) -> None:
    assert python_profile().test_module_name(path) == module


@pytest.mark.parametrize(
    ("path", "is_source"),
    [
        ("src/app/store.py", True),
        ("tests/test_store.py", False),
        ("tests/store_test.py", False),
        ("tests/conftest.py", False),
        ("tests/helpers.py", False),
    ],
)
def test_only_a_non_test_python_path_is_a_source_module(path: str, is_source: bool) -> None:
    assert python_profile().is_source_module(path) is is_source
