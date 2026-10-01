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


@pytest.mark.parametrize("prompt", [REVIEW_FEEDBACK_PROMPT, REWORK_PROMPT])
def test_a_rework_adds_commits_and_never_rewrites_history(prompt: str) -> None:
    assert "Do not rewrite history" in prompt
    assert "new commits" in prompt
