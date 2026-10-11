"""Writing tests first does not pin a function that already exists (spec: dry-guidance).

The tests prompt decides reuse, generalize or create before it stubs a named
function; the implementing prompts may repoint a test whose stub duplicates
existing code; the reviewer counts a stub the tests commit added.
"""

import re

import pytest

from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from agent_build_kit.pipeline.stack_runner import (
    ADAPT_CONTINUATION,
    CHECKS_CONTINUATION,
    CHECKS_PROMPT,
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT
from tests.prompt_text import filled, flat, placeholders


def stub_paragraph() -> str:
    """The text of the tests prompt from its stub sentence to its stand-in paragraph."""
    text = flat(TESTS_PROMPT)
    start = text.index("Stubs contain no logic.")
    return text[start : text.index("Where a test needs a stand-in")].lower()


# 3.1 — decide before stubbing


def test_the_agent_searches_when_a_task_names_code_or_a_second_place_needs_the_logic() -> None:
    paragraph = stub_paragraph()

    assert "names code to add" in paragraph
    assert "second place" in paragraph
    assert re.search(r"search[^.]*existing equivalent|existing equivalent[^.]*search", paragraph)
    assert "three cases" in paragraph


def test_case_a_tests_through_the_existing_function_and_reports_the_reuse() -> None:
    paragraph = stub_paragraph()

    assert "(a)" in paragraph
    assert re.search(r"tests? through it", paragraph)
    assert "no stub" in paragraph
    assert "reused x instead of adding y" in paragraph


def test_case_b_targets_the_missing_behaviour_and_creates_no_new_name() -> None:
    paragraph = stub_paragraph()

    assert "(b)" in paragraph
    assert "nearly" in paragraph
    assert re.search(r"missing behaviou?r", paragraph)
    assert "no new name" in paragraph


def test_case_c_stubs_one_helper_at_the_shared_place_and_not_one_per_call_site() -> None:
    paragraph = stub_paragraph()

    assert "(c)" in paragraph
    assert re.search(r"one stub[^.]*shared", paragraph)
    assert "own interface" in paragraph
    assert "each call site" in paragraph
    assert re.search(r"no second copy[^.]*per call site", paragraph)


def test_the_nearest_entry_point_is_preferred_and_a_contract_name_is_stubbed_as_named() -> None:
    paragraph = stub_paragraph()

    assert re.search(r"nearest existing entry point[^.]*internal helper", paragraph)
    assert re.search(r"contract[^.]*stubbed as named", paragraph)


def test_the_paragraph_names_no_installation_language_tool_or_path() -> None:
    paragraph = stub_paragraph()

    assert "reused x instead of adding y" in paragraph
    assert not re.search(r"\w+#\d+|/home/|\b(src|tests)/|\.py\b|\.ts\b", paragraph)
    for tool in ("pytest", "npm", "ruff", "cargo", "jest", "vitest"):
        assert tool not in paragraph


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(IMPLEMENTATION_PROMPT, id="implementation"),
        pytest.param(CHECKS_PROMPT, id="checks"),
        pytest.param(REWORK_PROMPT, id="rework"),
        pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
        pytest.param(IMPLEMENTATION_CONTINUATION, id="implementation-continuation"),
        pytest.param(CHECKS_CONTINUATION, id="checks-continuation"),
        pytest.param(REWORK_CONTINUATION, id="rework-continuation"),
        pytest.param(REVIEW_FEEDBACK_CONTINUATION, id="review-feedback-continuation"),
        pytest.param(ADAPT_CONTINUATION, id="adapt-continuation"),
    ],
)
def test_the_paragraph_is_in_the_tests_prompt_only(prompt: str) -> None:
    assert "reused x instead of adding y" in stub_paragraph()
    assert "instead of adding" not in flat(prompt).lower()


# 3.2 — red check


def test_new_tests_go_in_files_where_every_test_fails() -> None:
    paragraph = stub_paragraph()

    assert re.search(r"test files? (in which|where|whose) every test fails", paragraph)
    assert re.search(r"not add(ed)? a failing test to a file that holds passing", paragraph)


def test_a_conversion_with_no_new_behaviour_observes_the_call_site_reaching_the_function() -> None:
    paragraph = stub_paragraph()

    assert re.search(r"no new behaviou?r", paragraph)
    assert re.search(r"call site reach(es|ing)[^.]*(shared|existing) function", paragraph)


# 3.3 — repointing

IMPLEMENTING = [
    pytest.param(IMPLEMENTATION_PROMPT, id="full"),
    pytest.param(IMPLEMENTATION_CONTINUATION, id="continuation"),
]


@pytest.mark.parametrize("prompt", IMPLEMENTING)
def test_a_stub_that_duplicates_existing_code_is_deleted_and_the_test_repointed(
    prompt: str,
) -> None:
    text = flat(filled(prompt)).lower()

    assert re.search(r"stub[^.]*duplicates existing code", text)
    assert re.search(r"delete[^.]*stub", text)
    assert re.search(r"repoint[^.]*existing function[^.]*same assertions", text)
    assert "not weakening" in text
    assert re.search(r"summary[^.]*says so|say so in (your|the) summary", text)
    assert "Do not weaken or delete a test to make it pass" in flat(prompt)


def test_the_continuation_still_fills_in_and_the_line_adds_no_braces() -> None:
    assert placeholders(IMPLEMENTATION_CONTINUATION) == {"changelog"}
    assert "repoint" in IMPLEMENTATION_CONTINUATION
    assert "MARKER" in IMPLEMENTATION_CONTINUATION.format(changelog="MARKER")


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(CHECKS_CONTINUATION, id="checks"),
        pytest.param(REVIEW_FEEDBACK_CONTINUATION, id="review-feedback"),
        pytest.param(REWORK_CONTINUATION, id="rework"),
        pytest.param(ADAPT_CONTINUATION, id="adapt"),
    ],
)
def test_no_other_continuation_carries_the_line(prompt: str) -> None:
    assert "repoint" in IMPLEMENTATION_CONTINUATION
    assert "repoint" not in flat(prompt).lower()


def test_the_reuse_part_is_still_not_repeated_in_the_implementation_continuation() -> None:
    assert "repoint" in IMPLEMENTATION_CONTINUATION
    assert flat(reuse_guidance()) not in flat(IMPLEMENTATION_CONTINUATION)


# 3.4 — the reviewer


def prior_art_step() -> str:
    bullets = [flat(b).lower() for b in REVIEW_PROMPT.split("\n- **")]
    held = [b for b in bullets if "existing equivalent" in b]
    assert held, "the review prompt has no prior-art step"
    return held[0]


def test_a_stub_or_helper_added_by_the_tests_commit_counts_as_added_by_the_change() -> None:
    step = prior_art_step()

    assert re.search(r"stub or helper[^.]*tests commit[^.]*(counts|added by the change)", step)


def test_a_test_repointed_with_unchanged_assertions_is_not_a_finding() -> None:
    step = prior_art_step()

    assert re.search(r"repointed at an existing function[^.]*unchanged assertions", step)
    assert "not a finding" in step
