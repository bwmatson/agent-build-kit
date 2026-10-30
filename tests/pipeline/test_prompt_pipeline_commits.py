"""What the first prompt of every session that edits a worktree says about committing: the
pipeline commits the work, the agent runs no command that makes a commit, and the commits that
exist stay as they are. The prompt that continues a session does not say it again (spec:
build-agent-does-not-commit)."""

import pytest

from agent_build_kit.pipeline.stack_runner import (
    ADAPT_CONTINUATION,
    ADAPT_PROMPT,
    CHECKS_CONTINUATION,
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    TESTS_PROMPT,
)

# What a session starts with, and what each later step says to the session it continues.
CONTINUATIONS = [
    pytest.param(IMPLEMENTATION_CONTINUATION, id="implement"),
    pytest.param(CHECKS_CONTINUATION, id="checks"),
    pytest.param(REVIEW_FEEDBACK_CONTINUATION, id="review-feedback"),
    pytest.param(REWORK_CONTINUATION, id="rework"),
    pytest.param(ADAPT_CONTINUATION, id="adapt"),
]
EDITING = [
    pytest.param(TESTS_PROMPT, id="tests"),
    pytest.param(IMPLEMENTATION_PROMPT, id="implement"),
    pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
    pytest.param(REWORK_PROMPT, id="rework"),
    pytest.param(ADAPT_PROMPT, id="adapt"),
]
REWRITING = [
    pytest.param(REVIEW_FEEDBACK_PROMPT, id="review-feedback"),
    pytest.param(REWORK_PROMPT, id="rework"),
]


def said(prompt: str) -> str:
    """The prompt on one line, so a wrapped sentence matches."""
    return " ".join(prompt.split())


@pytest.mark.parametrize("prompt", EDITING)
def test_every_editing_prompt_says_the_pipeline_commits_the_work(prompt: str) -> None:
    text = said(prompt)

    assert "The pipeline commits your work" in text
    assert "leave your changes in the working tree" in text
    assert "run no command that makes a commit" in text


@pytest.mark.parametrize("prompt", EDITING)
def test_no_editing_prompt_calls_the_agents_work_new_commits(prompt: str) -> None:
    assert "new commits" not in said(prompt)
    assert "Your work is new commits" not in said(prompt)


@pytest.mark.parametrize("prompt", REWRITING)
def test_the_prompts_that_forbid_rewriting_history_say_the_commits_that_exist_stay(
    prompt: str,
) -> None:
    text = said(prompt)

    assert "Do not rewrite history" in text
    assert "the commits that exist stay as they are" in text


@pytest.mark.parametrize("prompt", CONTINUATIONS)
def test_the_prompt_that_continues_a_session_does_not_say_it_again(prompt: str) -> None:
    """A continued session already holds the first prompt."""
    text = said(prompt)

    assert "The pipeline commits your work" not in text
    assert "run no command that makes a commit" not in text
