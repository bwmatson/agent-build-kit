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


REQUEST = "Squash the two fixup commits into the commit they repair."
FIELDS = {
    "change_dir": "/planning/openspec/changes/feature",
    "groups": "1",
    "feedback": "the history is noisy",
    "boundary": "",
    "changelog": "",
    "pr": "7",
}


def first_prompt(template: str, request: str = "") -> str:
    """A first prompt of a review-feedback or rework step, with a rewrite request's text when
    one is given."""
    return said(template.format(**FIELDS, rewrite_request=request))


@pytest.mark.parametrize("template", REWRITING)
def test_the_first_prompt_of_a_step_with_a_rewrite_request_carries_its_text(
    template: str,
) -> None:
    assert REQUEST in first_prompt(template, REQUEST)


@pytest.mark.parametrize("template", REWRITING)
def test_the_first_prompt_with_a_rewrite_request_allows_own_commits_and_never_the_base(
    template: str,
) -> None:
    text = first_prompt(template, REQUEST)

    assert "may be rewritten" in text
    assert "never the base" in text


@pytest.mark.parametrize("template", REWRITING)
def test_the_first_prompt_with_a_rewrite_request_says_tests_stay_before_implementation(
    template: str,
) -> None:
    assert "tests stay before implementation" in first_prompt(template, REQUEST)


@pytest.mark.parametrize("template", REWRITING)
def test_the_first_prompt_with_a_rewrite_request_drops_the_sentences_that_forbid_a_rewrite(
    template: str,
) -> None:
    text = first_prompt(template, REQUEST)

    assert "Do not rewrite history" not in text
    assert "run no command that makes a commit" not in text


@pytest.mark.parametrize("template", REWRITING)
def test_the_first_prompt_with_no_rewrite_request_is_as_before(template: str) -> None:
    text = first_prompt(template, "")

    assert text == said(template.format(**FIELDS))
    assert "Do not rewrite history" in text
    assert text != first_prompt(template, REQUEST)


@pytest.mark.parametrize(
    ("first", "continuation"),
    [
        pytest.param(REVIEW_FEEDBACK_PROMPT, REVIEW_FEEDBACK_CONTINUATION, id="review-feedback"),
        pytest.param(REWORK_PROMPT, REWORK_CONTINUATION, id="rework"),
    ],
)
def test_the_prompt_that_continues_a_session_does_not_repeat_the_rewrite_request(
    first: str, continuation: str
) -> None:
    assert REQUEST in first_prompt(first, REQUEST)

    text = said(continuation.format(**FIELDS, rewrite_request=REQUEST))

    assert REQUEST not in text
    assert "may be rewritten" not in text
