"""What the agents are told about the changelog.

The convention is the body of the `## Changelog` section of the AGENTS.md in the
repository being built, and the prompts of the agents that write an entry carry
that text; a repository with no such section is told nothing.
"""

import re
from pathlib import Path

from agent_build_kit.pipeline.changelog_convention import (
    changelog_convention,
    changelog_note,
    resolver_changelog_rule,
    review_changelog_paragraph,
)
from agent_build_kit.pipeline.restack import RESOLVE_PROMPT
from agent_build_kit.pipeline.stack_runner import (
    IMPLEMENTATION_PROMPT,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

ROOT = Path(__file__).resolve().parents[2]

FIXTURE_CONVENTION = "Keep a bullet per change under `## Unreleased`, with {braces} in it."


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def repo_with(tmp_path: Path, section: str | None) -> Path:
    """A fixture repo whose AGENTS.md has a `## Changelog` section, or none."""
    text = "# app\n\n## Layout\n\nsrc/\n"
    if section is not None:
        text += f"\n## Changelog\n\n{section}\n\n## Running\n\nrun it\n"
    (tmp_path / "AGENTS.md").write_text(text)
    return tmp_path


def resolve_prompt(worktree: Path, files: list[str]) -> str:
    return RESOLVE_PROMPT.format(
        moving_unit="a",
        moving_intent="b",
        onto_unit="c",
        onto_intent="d",
        files="\n".join(f"- {name}" for name in files),
        replayed="",
        diff="",
        changelog_rule=resolver_changelog_rule(worktree, files),
        changelog=changelog_note(worktree),
    )


def build_prompts(worktree: Path) -> list[str]:
    fields = {
        "groups": "1",
        "change_dir": "c",
        "boundary": "",
        "feedback": "f",
        "pr": "p",
        "changelog": changelog_note(worktree),
    }
    prompts = [IMPLEMENTATION_PROMPT, REVIEW_FEEDBACK_PROMPT, REWORK_PROMPT]
    return [*(prompt.format(**fields) for prompt in prompts), resolve_prompt(worktree, ["x.py"])]


def test_the_convention_is_stated_in_the_conventions_file() -> None:
    text = changelog_convention(ROOT).lower()

    assert "unreleased" in text
    assert "blank line" in text
    assert "pull request" in text or "pull-request" in text
    assert "beside the bullets for related work" in text
    assert "never names an installation" in text
    assert "pull-request or issue number" in text
    assert "dated story" in text


def test_each_prompt_carries_the_text_of_a_repos_own_section(tmp_path: Path) -> None:
    for prompt in build_prompts(repo_with(tmp_path, FIXTURE_CONVENTION)):
        assert FIXTURE_CONVENTION in prompt


def test_each_prompt_carries_this_repos_text_when_it_is_the_one_built() -> None:
    for prompt in build_prompts(ROOT):
        assert squeezed(changelog_convention(ROOT)) in squeezed(prompt)


def test_a_repo_with_no_section_gets_no_changelog_convention(tmp_path: Path) -> None:
    worktree = repo_with(tmp_path, None)

    for prompt in build_prompts(worktree):
        assert "changelog" not in prompt.lower()
    assert review_changelog_paragraph(worktree) == ""


def test_a_repo_with_no_agents_file_gets_none_either(tmp_path: Path) -> None:
    assert changelog_convention(tmp_path) == ""
    assert changelog_note(tmp_path) == ""


def test_the_resolver_is_told_to_keep_both_sides_and_fold_one_change(tmp_path: Path) -> None:
    prompt = squeezed(resolve_prompt(tmp_path, ["CHANGELOG.md"])).lower()

    assert "both sides' bullets" in prompt
    assert "fold" in prompt
    assert "same bullet" in prompt


def test_the_keep_both_rule_appears_only_where_a_changelog_is_in_play(tmp_path: Path) -> None:
    bare = repo_with(tmp_path, None)

    assert resolver_changelog_rule(bare, ["x.py"]) == ""
    assert "fold" in resolver_changelog_rule(bare, ["CHANGELOG.md"])
    assert "fold" in resolver_changelog_rule(repo_with(tmp_path, "text"), ["x.py"])


def changelog_paragraphs(prompt: str) -> str:
    """What the review prompt says in the paragraphs that mention the changelog."""
    paragraphs = re.split(r"\n\s*\n|\n- ", prompt)
    return squeezed(" ".join(p for p in paragraphs if "changelog" in p.lower())).lower()


def test_the_review_prompt_leaves_form_and_wording_to_the_repos_checks(tmp_path: Path) -> None:
    said = changelog_paragraphs(review_changelog_paragraph(repo_with(tmp_path, "text")))

    assert "form" in said
    assert "wording" in said


def test_the_review_prompt_still_raises_a_changelog_claim_the_code_does_not_support(
    tmp_path: Path,
) -> None:
    said = changelog_paragraphs(review_changelog_paragraph(repo_with(tmp_path, "text")))

    assert "claim" in said
    assert "support" in said


def test_the_standing_review_prompt_says_nothing_of_the_changelog() -> None:
    assert "changelog" not in REVIEW_PROMPT.lower()
