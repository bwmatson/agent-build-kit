"""The python-uv profile's red words: what its tests prompt says counts as red, built from the
red check's own sets (spec: tdd-loop)."""

from __future__ import annotations

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.red_check import ACCEPTED_TYPES, MISSING_NAMES
from agent_build_kit.profiles.base import ReadsTestShape


def python_profile() -> ReadsTestShape:
    profile = profiles.get("python-uv")
    assert isinstance(profile, ReadsTestShape)
    return profile


@pytest.mark.parametrize("stubbed", [True, False], ids=["stubbed", "unstubbed"])
def test_the_red_words_follow_the_red_checks_sets(stubbed: bool) -> None:
    words = profiles.get("python-uv").prompt_words
    words = words.red_stubbed if stubbed else words.red
    expected = set(ACCEPTED_TYPES) - (set(MISSING_NAMES) if stubbed else set())
    not_red = " ".join(words.not_red)

    assert set(words.red_types) == expected
    if stubbed:
        assert all(name in not_red for name in MISSING_NAMES)
    for word in ("conftest", "collected", "pytest.raises"):
        assert word in not_red
    assert "stub" in words.advice


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
        ("docs/readme.md", False),
    ],
)
def test_only_a_non_test_python_path_is_a_source_module(path: str, is_source: bool) -> None:
    assert python_profile().is_source_module(path) is is_source


def test_a_file_that_is_not_python_has_no_tests_and_is_readable() -> None:
    read = python_profile().read_test_file("tests/data.json", "{not python")
    assert read.readable
    assert read.tests == ()
