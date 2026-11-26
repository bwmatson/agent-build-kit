"""What the builders are told about the test standards.

One packaged table, carried by the full form of the tests, implementation and rework prompts
and by no continuation prompt (spec: test-standards-guidance).
"""

import re

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    TESTS_FINISH,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.standards_guidance import standards_guidance
from agent_build_kit.pipeline.wiring import review_prompt
from tests.prompt_text import filled, flat

STANDARD_IDS = [*(f"T{n}" for n in range(1, 28)), "T8a", "T12a"]

BUILDERS = [
    pytest.param(TESTS_PROMPT, id="tests"),
    pytest.param(IMPLEMENTATION_PROMPT, id="implementation"),
    pytest.param(REWORK_PROMPT, id="rework"),
]

CONTINUATIONS = [
    pytest.param(IMPLEMENTATION_CONTINUATION, id="implementation"),
    pytest.param(REWORK_CONTINUATION, id="rework"),
]


def table_lines() -> dict[str, str]:
    """The table's standards by ID, each with its whole line."""
    lines = [line.strip() for line in standards_guidance().splitlines()]
    return {m.group(1): line for line in lines if (m := re.match(r"(T\d+a?) \S", line))}


def test_the_table_has_a_line_for_every_standard() -> None:
    lines = table_lines()

    assert sorted(lines) == sorted(STANDARD_IDS)
    for standard_id, line in lines.items():
        assert len(line) > len(standard_id) + 10, f"{standard_id} has a rule"


def test_the_table_asks_for_the_id_to_be_cited_in_the_summary() -> None:
    text = flat(standards_guidance()).lower()

    assert "cite the id" in text
    assert "summary" in text


def test_the_table_is_under_2500_bytes() -> None:
    assert len(standards_guidance().encode()) < 2500


def test_the_table_has_no_braces_to_break_the_filling() -> None:
    text = standards_guidance()

    assert not set("{}") & set(text)


@pytest.mark.parametrize("prompt", BUILDERS)
def test_a_new_session_prompt_carries_the_table_once(prompt: str) -> None:
    text = flat(filled(prompt))

    assert flat(standards_guidance()) in text
    assert text.count(flat(table_lines()["T1"])) == 1
    for line in table_lines().values():
        assert flat(line) in text


@pytest.mark.parametrize("prompt", CONTINUATIONS)
def test_a_continuation_prompt_carries_neither_table_nor_request(prompt: str) -> None:
    text = flat(filled(prompt))

    assert flat(standards_guidance()) not in text
    assert flat(table_lines()["T1"]) not in text
    assert "cite the id" not in text.lower()


PYTHON_PLACEMENT = profiles.get("python-uv").prompt_words.placement

PROMPT_TEXTS = {
    "tests": lambda: filled(TESTS_PROMPT, placement=PYTHON_PLACEMENT),
    "implementation": lambda: filled(IMPLEMENTATION_PROMPT),
    "rework": lambda: filled(REWORK_PROMPT),
    "review": lambda: review_prompt({"feature/1": GroupMode.TESTS_AND_CODE}),
}

# Each directive by a short key phrase, in the lower case of the squeezed prompt.
DIRECTIVES = {
    "one test file per module": "test_<module>.py",
    "new test file only for a new source file": "new source file",
    "extend before adding": "extend an existing test or add a case",
    "one scenario, one test": "one scenario, one test",
    "properties, not prose": "assert properties, not prose",
    "no wording test": "no wording test except an exclusion guard or a prompt's directive table",
    "fake at a boundary": "fake at a boundary",
}


@pytest.mark.parametrize("directive", DIRECTIVES)
@pytest.mark.parametrize("prompt", PROMPT_TEXTS)
def test_each_prompt_carries_each_directive_on_extending_tests(prompt: str, directive: str) -> None:
    text = flat(PROMPT_TEXTS[prompt]()).lower()

    assert DIRECTIVES[directive] in text


# What the tests prompt alone says about the red check: the rest of the table is carried by
# every prompt that writes or reviews tests.
TESTS_PROMPT_DIRECTIVES = [
    "a new test and a changed assertion must fail",
    "a test changed only in setup, names or helpers may pass",
]


@pytest.mark.parametrize("directive", TESTS_PROMPT_DIRECTIVES)
def test_the_tests_prompt_for_a_python_repo_says_which_tests_must_fail_and_which_may_pass(
    directive: str,
) -> None:
    text = flat(filled(TESTS_PROMPT, placement=PYTHON_PLACEMENT, finish=TESTS_FINISH)).lower()

    assert directive in text


def test_the_tests_prompt_for_a_python_repo_places_new_cases_in_the_existing_file() -> None:
    text = flat(PROMPT_TEXTS["tests"]()).lower()

    assert "extend an existing test or add a case before adding a test" in text
    assert "files in which every test fails" not in text
    assert "which must fail" not in text
    assert "every new test must fail" not in text


def test_the_placement_rule_cites_its_standards_once_and_a_whole_file_profile_has_no_init() -> None:
    node = profiles.get("node-npm").prompt_words.placement

    for standard in ("T2", "T3", "T21"):
        assert len(re.findall(rf"\b{standard}\b", PYTHON_PLACEMENT)) == 1
    assert "__init__.py" not in node
