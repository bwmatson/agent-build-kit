"""The skill, the architecture document and the changelog say how a group's floor reads each of
its tasks (spec: group-floor-reads-every-task)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed, unreleased_bullets

SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-authoring" / "SKILL.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"


def test_the_skill_says_a_task_that_changes_code_names_its_file() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))
    start = text.index("Name the file a task changes.")
    paragraph = text[start : start + 900]

    assert "Confirm, Check, Verify, Read or Run" in paragraph
    assert "tests first and then code" in paragraph
    assert "Tests: required" in paragraph


def test_the_architecture_document_says_what_makes_a_group_test_only() -> None:
    text = squashed(ARCHITECTURE.read_text(encoding="utf-8"))
    start = text.index("What makes a group test-only.")
    paragraph = text[start : start + 1100]

    assert "every task" in paragraph and "Paths:" in paragraph
    assert "names a path" in paragraph and "not what the path is" in paragraph


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "tests-only or no-code only when each of its tasks is placed" in bullet
        for bullet in unreleased_bullets()
    )
