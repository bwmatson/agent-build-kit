"""The documents, the skills and the changelog describe the size hold and the split (spec:
a-unit-over-its-tier-is-held-and-split)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.doc_text import ROOT, squashed, unreleased_bullets

DOCS = ROOT / "docs"
SKILLS = Path(skills.SKILLS_DIR)


def read(path: Path) -> str:
    return squashed(path.read_text(encoding="utf-8"))


def test_the_configuration_document_and_config_skill_name_the_two_settings() -> None:
    for path in (DOCS / "configuration.md", SKILLS / "abk-config" / "SKILL.md"):
        text = read(path)
        assert re.search(r"ceiling_buffer\b.{0,200}0\.2", text), path
        assert re.search(r"split_rounds\b.{0,200}\b2\b", text), path
        assert re.search(r"reading limit.{0,80}10,?000", text, re.I), path


def test_the_architecture_and_graph_documents_name_the_causes_and_the_ref() -> None:
    for path in (DOCS / "architecture.md", DOCS / "unit-graph.md"):
        text = read(path)
        assert "too_big_for_tier" in text, path
        assert re.search(r"closed.{0,120}superseded|superseded.{0,120}closed", text), path
        assert "refs/spec-driven/superseded/" in text, path
        assert re.search(r"held by size|held_by size|HeldBy\.SIZE", text, re.I), path


def test_the_cli_document_and_pipeline_skill_name_the_two_holds_and_the_waiver() -> None:
    for path in (DOCS / "cli.md", SKILLS / "abk-pipeline" / "SKILL.md"):
        text = read(path)
        assert re.search(r"held by size", text, re.I), path
        assert re.search(r"held for a person", text, re.I), path
        assert "size_waived" in text, path
        assert re.search(r"requeue.{0,200}(waive|size_waived)", text, re.I), path


def test_the_authoring_skill_names_drivers_and_says_tasks_md_is_not_changed() -> None:
    text = read(SKILLS / "abk-authoring" / "SKILL.md")
    assert re.search(r"driver", text, re.I)
    assert re.search(r"split.{0,200}tasks\.md.{0,80}(not|need not|never).{0,40}chang", text, re.I)


def test_the_changelog_says_a_unit_over_its_buffered_ceiling_is_replaced_by_smaller_units() -> None:
    bullets = unreleased_bullets()
    assert any(
        re.search(r"buffered ceiling", b) and re.search(r"smaller units", b, re.I) for b in bullets
    )
