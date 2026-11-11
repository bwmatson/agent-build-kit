"""What every prompt that gives an agent a worktree says about pushing."""

import pytest

from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT


@pytest.mark.parametrize(
    "prompt",
    [TESTS_PROMPT, IMPLEMENTATION_PROMPT, REVIEW_FEEDBACK_PROMPT, REWORK_PROMPT, REVIEW_PROMPT],
)
def test_every_prompt_says_the_pipeline_pushes_and_the_agent_never_does(prompt: str) -> None:
    assert "never push" in prompt or "you never do" in prompt


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
        pytest.param(REWORK_PROMPT, id="rework"),
    ],
)
def test_a_rework_never_rewrites_history_and_leaves_the_commit_to_the_pipeline(
    prompt: str,
) -> None:
    assert "Do not rewrite history" in prompt
    assert "new commits" not in prompt


@pytest.mark.parametrize("prompt", [TESTS_PROMPT, IMPLEMENTATION_PROMPT])
def test_the_tests_and_implement_prompts_say_a_refused_call_did_not_run(prompt: str) -> None:
    text = " ".join(prompt.split()).lower()

    assert "refused" in text
    assert "did not run" in text
    assert "not reported" in text or "do not report" in text


@pytest.mark.parametrize("prompt", [TESTS_PROMPT, IMPLEMENTATION_PROMPT])
def test_the_tests_and_implement_prompts_say_to_write_files_with_the_edit_tool(
    prompt: str,
) -> None:
    text = " ".join(prompt.split()).lower()

    assert "edit tool" in text
    assert "redirection" in text
