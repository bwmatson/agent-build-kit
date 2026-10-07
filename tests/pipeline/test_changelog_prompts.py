"""What the agents are told about the changelog.

The convention is the body of the `## Changelog` section of the repository being
built, from its AGENTS.md or else its CLAUDE.md; a repository with neither is
told the framework's packaged text, and one with the setting off is told nothing.
"""

import re
from importlib import resources
from pathlib import Path

from agent_build_kit.config import RepoConfig
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
    TESTS_PROMPT,
)
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

ROOT = Path(__file__).resolve().parents[2]

FIXTURE_CONVENTION = "Keep a bullet per change under `## Unreleased`, with {braces} in it."
OTHER_CONVENTION = "Put each entry at the top of the file."


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def packaged() -> str:
    """The framework's own convention text, as shipped in the package."""
    return (
        resources.files("agent_build_kit")
        .joinpath("templates", "changelog-convention.md")
        .read_text()
        .strip()
    )


def on(path: Path) -> RepoConfig:
    return RepoConfig(path=path, slug="example/app")


def off(path: Path) -> RepoConfig:
    return RepoConfig(path=path, slug="example/app", changelog=None)


def repo_with(tmp_path: Path, section: str | None, *, file: str = "AGENTS.md") -> Path:
    """A fixture repo whose conventions file has a `## Changelog` section, or none."""
    text = "# app\n\n## Layout\n\nsrc/\n"
    if section is not None:
        text += f"\n## Changelog\n\n{section}\n\n## Running\n\nrun it\n"
    (tmp_path / file).write_text(text)
    return tmp_path


def resolve_prompt(worktree: Path, files: list[str], repo: RepoConfig) -> str:
    return RESOLVE_PROMPT.format(
        moving_unit="a",
        moving_intent="b",
        onto_unit="c",
        onto_intent="d",
        files="\n".join(f"- {name}" for name in files),
        replayed="",
        diff="",
        changelog_rule=resolver_changelog_rule(worktree, files, repo),
        changelog=changelog_note(worktree, repo),
    )


def build_prompts(worktree: Path, repo: RepoConfig) -> list[str]:
    fields = {
        "groups": "1",
        "change_dir": "c",
        "boundary": "",
        "feedback": "f",
        "pr": "p",
        "changelog": changelog_note(worktree, repo),
    }
    prompts = [TESTS_PROMPT, IMPLEMENTATION_PROMPT, REVIEW_FEEDBACK_PROMPT, REWORK_PROMPT]
    return [
        *(prompt.format(**fields) for prompt in prompts),
        resolve_prompt(worktree, ["x.py"], repo),
    ]


def test_the_convention_is_stated_in_the_conventions_file() -> None:
    text = changelog_convention(ROOT, on(ROOT)).lower()

    assert "unreleased" in text
    assert "blank line" in text
    assert "pull request" in text or "pull-request" in text
    assert "beside the bullets for related work" in text
    assert "never names an installation" in text
    assert "pull-request or issue number" in text
    assert "dated story" in text


def test_the_packaged_text_states_the_convention_and_names_no_installation() -> None:
    text = squeezed(packaged()).lower()

    assert "unreleased" in text
    assert "blank line" in text
    assert "installation" in text
    assert "issue number" in text
    assert "dated" in text
    assert "union" in text
    assert not re.search(r"\w+#\d+", text)
    assert "/home/" not in text


def test_a_repos_own_agents_section_is_its_convention(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, FIXTURE_CONVENTION)

    assert changelog_convention(repo, on(repo)) == FIXTURE_CONVENTION


def test_a_claude_section_is_read_where_agents_has_none(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, None)
    repo_with(tmp_path, OTHER_CONVENTION, file="CLAUDE.md")

    assert changelog_convention(repo, on(repo)) == OTHER_CONVENTION


def test_agents_wins_over_claude_when_both_have_a_section(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, FIXTURE_CONVENTION)
    repo_with(tmp_path, OTHER_CONVENTION, file="CLAUDE.md")

    assert changelog_convention(repo, on(repo)) == FIXTURE_CONVENTION


def test_a_repo_with_no_section_gets_the_packaged_text(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, None)
    repo_with(tmp_path, None, file="CLAUDE.md")

    assert changelog_convention(repo, on(repo)) == packaged()


def test_a_repo_with_no_conventions_files_gets_the_packaged_text(tmp_path: Path) -> None:
    assert changelog_convention(tmp_path, on(tmp_path)) == packaged()
    assert squeezed(packaged()) in squeezed(changelog_note(tmp_path, on(tmp_path)))


def test_a_repo_with_the_changelog_off_gets_no_convention_even_with_a_section(
    tmp_path: Path,
) -> None:
    for repo in (repo_with(tmp_path, None), repo_with(tmp_path, FIXTURE_CONVENTION)):
        assert changelog_convention(repo, off(repo)) == ""
        assert changelog_note(repo, off(repo)) == ""


def test_each_prompt_carries_the_text_of_a_repos_own_section(tmp_path: Path) -> None:
    worktree = repo_with(tmp_path, FIXTURE_CONVENTION)

    for prompt in build_prompts(worktree, on(worktree)):
        assert FIXTURE_CONVENTION in prompt


def test_each_prompt_carries_this_repos_text_when_it_is_the_one_built() -> None:
    for prompt in build_prompts(ROOT, on(ROOT)):
        assert squeezed(changelog_convention(ROOT, on(ROOT))) in squeezed(prompt)


def test_each_prompt_carries_the_packaged_text_for_a_repo_with_no_section(
    tmp_path: Path,
) -> None:
    worktree = repo_with(tmp_path, None)

    for prompt in build_prompts(worktree, on(worktree)):
        assert squeezed(packaged()) in squeezed(prompt)


def test_a_repo_with_the_changelog_off_gets_no_changelog_in_any_prompt(tmp_path: Path) -> None:
    worktree = repo_with(tmp_path, FIXTURE_CONVENTION)

    for prompt in build_prompts(worktree, off(worktree)):
        assert "changelog" not in prompt.lower()
        assert FIXTURE_CONVENTION not in prompt
    assert review_changelog_paragraph(worktree, off(worktree)) == ""


def test_the_resolver_is_told_to_keep_both_sides_and_fold_one_change(tmp_path: Path) -> None:
    worktree = repo_with(tmp_path, None)
    prompt = squeezed(resolve_prompt(worktree, ["CHANGELOG.md"], on(worktree))).lower()

    assert "both sides' bullets" in prompt
    assert "fold" in prompt
    assert "same bullet" in prompt


def test_the_keep_both_rule_applies_to_every_repo_with_the_setting_on(tmp_path: Path) -> None:
    bare = repo_with(tmp_path, None)

    assert "fold" in resolver_changelog_rule(bare, ["x.py"], on(bare))
    assert "fold" in resolver_changelog_rule(bare, ["CHANGELOG.md"], on(bare))
    assert "fold" in resolver_changelog_rule(repo_with(tmp_path, "text"), ["x.py"], on(bare))


def test_the_keep_both_rule_is_absent_where_the_setting_is_off(tmp_path: Path) -> None:
    bare = repo_with(tmp_path, None)

    assert resolver_changelog_rule(bare, ["x.py"], off(bare)) == ""
    assert resolver_changelog_rule(bare, ["CHANGELOG.md"], off(bare)) == ""


def changelog_paragraphs(prompt: str) -> str:
    """What the review prompt says in the paragraphs that mention the changelog."""
    paragraphs = re.split(r"\n\s*\n|\n- ", prompt)
    return squeezed(" ".join(p for p in paragraphs if "changelog" in p.lower())).lower()


def test_the_review_prompt_covers_a_repo_with_no_section_of_its_own(tmp_path: Path) -> None:
    bare = repo_with(tmp_path, None)

    assert changelog_paragraphs(review_changelog_paragraph(bare, on(bare)))


def test_the_review_prompt_leaves_form_and_wording_to_the_repos_checks(tmp_path: Path) -> None:
    worktree = repo_with(tmp_path, "text")
    said = changelog_paragraphs(review_changelog_paragraph(worktree, on(worktree)))

    assert "form" in said
    assert "wording" in said


def test_the_review_prompt_still_raises_a_changelog_claim_the_code_does_not_support(
    tmp_path: Path,
) -> None:
    worktree = repo_with(tmp_path, "text")
    said = changelog_paragraphs(review_changelog_paragraph(worktree, on(worktree)))

    assert "claim" in said
    assert "support" in said


def test_the_standing_review_prompt_says_nothing_of_the_changelog() -> None:
    assert "changelog" not in REVIEW_PROMPT.lower()
