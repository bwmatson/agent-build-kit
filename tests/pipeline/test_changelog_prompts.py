"""What the agents are told about the changelog.

The convention is written once, in the repository's conventions file, and the
prompts of the agents that write an entry carry that text.
"""

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import RESOLVE_PROMPT
from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

ROOT = Path(__file__).resolve().parents[2]


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def convention() -> str:
    """The body of the conventions file's changelog section."""
    text = (ROOT / "AGENTS.md").read_text()
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    found = [s for s in sections if s.splitlines()[0].lower().startswith("changelog")]
    assert found, "AGENTS.md has no `## Changelog…` section"
    return squeezed("\n".join(found[0].splitlines()[1:]))


def test_the_convention_is_stated_in_the_conventions_file() -> None:
    text = convention().lower()

    assert "unreleased" in text
    assert "blank line" in text
    assert "pull request" in text or "pull-request" in text


@pytest.mark.parametrize(
    "prompt", [IMPLEMENTATION_PROMPT, REVIEW_FEEDBACK_PROMPT, REWORK_PROMPT, RESOLVE_PROMPT]
)
def test_the_prompt_carries_the_convention_text(prompt: str) -> None:
    assert convention() in squeezed(prompt)


def test_the_resolver_is_told_to_keep_both_sides_and_fold_one_change() -> None:
    prompt = squeezed(RESOLVE_PROMPT).lower()

    assert "changelog" in prompt
    assert "keep both" in prompt or "keep every bullet" in prompt
    assert "fold" in prompt


def changelog_paragraphs(prompt: str) -> str:
    """What the review prompt says in the paragraphs that mention the changelog."""
    paragraphs = re.split(r"\n\s*\n|\n- ", prompt)
    return squeezed(" ".join(p for p in paragraphs if "changelog" in p.lower())).lower()


def test_the_review_prompt_leaves_the_changelogs_form_and_wording_to_tier_1() -> None:
    said = changelog_paragraphs(REVIEW_PROMPT)

    assert "form" in said
    assert "wording" in said
    assert "tier 1" in said


def test_the_review_prompt_still_raises_a_changelog_claim_the_code_does_not_support() -> None:
    said = changelog_paragraphs(REVIEW_PROMPT)

    assert "claim" in said
    assert "support" in said
