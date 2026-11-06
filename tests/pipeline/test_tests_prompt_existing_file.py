"""The tests prompt states where a new case goes, by the toolchain profile (spec: red-check-by-id).

A profile whose red check selects the added tests by id puts a new case in the existing test
file; one that runs whole files keeps new tests in files in which every test fails."""

import re

from agent_build_kit import profiles
from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from tests.prompt_text import filled, flat


def for_profile(profile: str) -> str:
    """The tests prompt as the build fills it for a repo on `profile`."""
    return filled(TESTS_PROMPT, placement=profiles.get(profile).prompt_words.placement)


def prompt(profile: str = "python-uv") -> str:
    return flat(for_profile(profile)).lower()


def test_a_new_case_goes_in_the_existing_test_file_for_the_module() -> None:
    text = prompt()

    assert "existing test file for the module it exercises" in text


def test_a_new_test_file_is_for_a_new_logic_file_only() -> None:
    text = prompt()

    assert "new test file is created only for a new logic file" in text
    assert "never a new file" in text


def test_one_subject_has_one_test_file_and_no_init() -> None:
    text = prompt()

    assert "one subject has one test file" in text
    assert "__init__.py" in text


def test_the_placement_rule_cites_its_standards_once() -> None:
    text = profiles.get("python-uv").prompt_words.placement

    for standard in ("T2", "T3", "T21"):
        assert len(re.findall(rf"\b{standard}\b", text)) == 1


def test_the_prompt_no_longer_keeps_new_tests_in_all_failing_files() -> None:
    text = prompt()

    assert "files in which every test fails" not in text
    assert "do not add a failing test to a file that holds passing ones" not in text


def test_the_prompt_does_not_say_every_new_test_must_fail() -> None:
    text = prompt()

    assert "which must fail" not in text
    assert "every new test must fail" not in text


def test_a_profile_that_runs_whole_files_keeps_new_tests_in_all_failing_files() -> None:
    text = prompt("node-npm")

    assert "test files in which every test fails before the implementation" in text
    assert "do not add a failing test to a file that holds passing ones" in text


def test_a_profile_that_runs_whole_files_is_not_told_to_add_a_case_to_an_existing_file() -> None:
    text = prompt("node-npm")

    assert "existing test file" not in text
    assert "__init__.py" not in text
