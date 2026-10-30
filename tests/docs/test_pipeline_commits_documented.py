"""The documents, the skill and the changelog say a build agent makes no commit and what stays
allowed (spec: build-agent-does-not-commit)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed, unreleased_bullets

RUNTIMES = ROOT / "docs" / "agent-runtimes.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return squashed(text[start : end if end != -1 else None])


def test_the_runtimes_document_has_a_section_on_the_pipeline_being_the_only_committer() -> None:
    text = section(RUNTIMES.read_text(encoding="utf-8"), "## Only the pipeline commits")

    assert "check_no_commit" in text
    assert "--no-commit" in text
    assert "cherry-pick" in text and "rebase" in text and "reset" in text
    for allowed in ("--no-commit", "--abort", "--quit"):
        assert allowed in text
    assert "restack" in text.lower() or "resolver" in text.lower()


def test_the_skill_says_what_the_build_agent_may_not_commit() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))
    start = text.index("What a build agent may do with git")
    heading = text[start : start + 900]

    assert "git commit" in heading and "refused" in heading
    assert "the pipeline commits" in heading


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "build agent" in bullet and "commit" in bullet and "refused" in bullet
        for bullet in unreleased_bullets()
    )
