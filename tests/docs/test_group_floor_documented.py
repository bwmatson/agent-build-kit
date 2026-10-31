"""The skill, the architecture document and the changelog say how a group's floor reads each of
its tasks (spec: group-floor-reads-every-task)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed, unreleased_bullets

SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-authoring" / "SKILL.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"


def test_the_skill_says_a_task_that_changes_code_names_its_file() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))
    start = text.index("Name the file a task changes.")
    paragraph = text[start : text.index("--", start) if "--" in text[start:] else start + 1500]

    assert "begins Confirm, Check, Verify or Read" in paragraph
    assert "tests first and then code" in paragraph
    assert "Tests: required" in paragraph
    assert "Paths: line" in paragraph and "turns the rule off" in paragraph


def test_the_architecture_document_says_what_makes_a_group_test_only() -> None:
    text = squashed(ARCHITECTURE.read_text(encoding="utf-8"))
    start = text.index("What makes a group test-only.")
    paragraph = text[start : text.index("An e2e-test group is never joined.", start)]

    assert (
        "every task is a Test: task, a check (it begins Confirm, Check, Verify or Read)"
        in paragraph
    )
    assert "A Paths: line says what the group names and turns the rule off" in paragraph
    assert "names a path, not what the path is" in paragraph


def test_the_changelog_has_a_bullet_for_it() -> None:
    bullets = [b for b in unreleased_bullets() if "each of its tasks is placed" in b]

    assert len(bullets) == 1
    assert "Confirm, Check, Verify or Read" in bullets[0]
    assert "Paths: line" in bullets[0]
