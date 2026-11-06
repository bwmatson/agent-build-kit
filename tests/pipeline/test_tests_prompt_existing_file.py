"""The tests prompt states where a new case goes (spec: red-check-by-id)."""

from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from tests.prompt_text import filled, flat


def prompt() -> str:
    return flat(filled(TESTS_PROMPT)).lower()


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
    text = filled(TESTS_PROMPT)

    for standard in ("T2", "T3", "T21"):
        assert text.count(standard) == 1


def test_the_prompt_no_longer_keeps_new_tests_in_all_failing_files() -> None:
    text = prompt()

    assert "files in which every test fails" not in text
    assert "do not add a failing test to a file that holds passing ones" not in text


def test_the_prompt_does_not_say_every_new_test_must_fail() -> None:
    text = prompt()

    assert "which must fail" not in text
    assert "every new test must fail" not in text
