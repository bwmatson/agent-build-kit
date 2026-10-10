"""What the builders are told about finding and reusing existing code.

One packaged, language-neutral part, carried by the full form of the prompts that
send an agent to change code and by no continuation prompt (spec: dry-guidance).
"""

import inspect
import re
import string

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from agent_build_kit.pipeline.stack_runner import (
    ADAPT_CONTINUATION,
    ADAPT_PROMPT,
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


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def filled(template: str) -> str:
    """The template with every placeholder filled in, as the nodes fill them."""
    names = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    return template.format(**dict.fromkeys(names, "x"))


BUILDERS = [
    pytest.param(TESTS_PROMPT, id="tests"),
    pytest.param(IMPLEMENTATION_PROMPT, id="implementation"),
    pytest.param(CHECKS_PROMPT, id="checks"),
    pytest.param(REWORK_PROMPT, id="rework"),
    pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
]

CONTINUATIONS = [
    pytest.param(IMPLEMENTATION_CONTINUATION, id="implementation"),
    pytest.param(CHECKS_CONTINUATION, id="checks"),
    pytest.param(REVIEW_FEEDBACK_CONTINUATION, id="review-feedback"),
    pytest.param(REWORK_CONTINUATION, id="rework"),
    pytest.param(ADAPT_CONTINUATION, id="adapt"),
]


@pytest.mark.parametrize("prompt", BUILDERS)
def test_each_builder_prompt_carries_the_part(prompt: str) -> None:
    assert squeezed(reuse_guidance()) in squeezed(prompt)


@pytest.mark.parametrize("prompt", BUILDERS)
def test_filling_a_prompt_in_leaves_the_part_unchanged(prompt: str) -> None:
    assert squeezed(reuse_guidance()) in squeezed(filled(prompt))


def test_the_part_has_no_braces_to_break_the_filling() -> None:
    text = reuse_guidance()

    assert text.strip()
    assert "{" not in text
    assert "}" not in text


def test_the_adapt_prompt_does_not_carry_the_part_and_keeps_its_own_instruction() -> None:
    text = squeezed(ADAPT_PROMPT)

    assert squeezed(reuse_guidance()) not in text
    assert "do not re-implement anything it already provides" in text


@pytest.mark.parametrize("prompt", CONTINUATIONS)
def test_a_continuation_prompt_does_not_repeat_the_part(prompt: str) -> None:
    assert squeezed(reuse_guidance()) not in squeezed(prompt)


def test_the_part_says_what_to_do() -> None:
    text = squeezed(reuse_guidance()).lower()

    assert re.search(r"search[^.]*before (adding|writing)", text), "search before adding"
    assert "use or extend" in text
    assert re.search(r"\bonce\b", text), "shared logic is written once"
    assert re.search(r"change together[^.]*one function|one function[^.]*change together", text)
    assert "shared test support" in text
    assert re.search(r"\bdead\b", text), "delete what the change makes dead"
    assert re.search(r"within the change|stay in scope|stay within", text)


def test_the_part_says_how_to_look() -> None:
    text = squeezed(reuse_guidance()).lower()

    assert "import" in text, "what the neighbouring code imports"
    for name in ("utils", "common", "shared", "lib", "helpers"):
        assert name in text
    assert "fixtures" in text, "the test runner's usual places"
    assert "convention" in text
    assert re.search(r"behaviou?r[^.]*as well as (by )?name", text)


def test_the_part_names_no_installation_language_tool_or_path() -> None:
    text = reuse_guidance()

    assert text.strip()
    assert "/home/" not in text
    assert not re.search(r"\w+#\d+", text)
    assert not re.search(r"\b(example|agent[-_]build[-_]kit|abk)\b", text, re.IGNORECASE)
    for tool in ("pytest", "uv ", "npm", "ruff", "cargo", "pip", "jest", "vitest"):
        assert tool not in text
    assert not re.search(r"\b(src|tests)/|\.py\b|\.ts\b|\.md\b", text)


def test_the_pipeline_reads_no_repository_section_for_the_part() -> None:
    assert not inspect.signature(reuse_guidance).parameters
    assert not [name for name in RepoConfig.model_fields if "reuse" in name]


def test_rework_adds_the_line_to_look_for_the_others_of_the_kind() -> None:
    pattern = r"look for (the )?others of the (same )?kind"

    assert re.search(pattern, squeezed(REWORK_PROMPT), re.IGNORECASE)
    assert re.search(pattern, squeezed(REWORK_CONTINUATION), re.IGNORECASE)


def test_review_feedback_and_checks_prompts_keep_their_wording() -> None:
    for prompt in (
        REVIEW_FEEDBACK_PROMPT,
        REVIEW_FEEDBACK_CONTINUATION,
        CHECKS_PROMPT,
        CHECKS_CONTINUATION,
    ):
        assert "look for others of the same kind" in squeezed(prompt)


def test_the_tests_prompt_points_to_the_shared_fixtures() -> None:
    assert "shared fixtures" in squeezed(TESTS_PROMPT).lower()
