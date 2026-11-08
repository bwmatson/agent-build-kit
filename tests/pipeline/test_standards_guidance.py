"""What the builders are told about the test standards.

One packaged table, carried by the full form of the tests, implementation and rework prompts
and by no continuation prompt (spec: test-standards-guidance).
"""

import re

import pytest

from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.standards_guidance import standards_guidance
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
