"""The documents describe the guards by class: where the step is confined a location guard
stands down, and a guard about meaning stays (spec: sandbox-guard-fallback)."""

from __future__ import annotations

import pytest

from tests.doc_text import ROOT, squashed

DOCUMENTS = [
    "docs/architecture.md",
    "docs/agent-runtimes.md",
    "docs/configuration.md",
    "docs/tracks.md",
    "src/agent_build_kit/skills/abk-config/SKILL.md",
]


def guard_passage(path: str) -> str:
    text = squashed((ROOT / path).read_text(encoding="utf-8")).lower()
    return text[text.index("guards by class") :] if "guards by class" in text else ""


@pytest.mark.parametrize("path", DOCUMENTS)
def test_the_document_has_a_guards_by_class_passage_naming_the_classes(path: str) -> None:
    passage = guard_passage(path)

    assert passage, f"{path} has no 'guards by class' passage"
    assert "location" in passage
    assert "meaning" in passage
    assert "confined" in passage
    assert "sandbox-design.md" in passage


def test_the_design_document_names_the_table_in_code_the_listing_reads() -> None:
    text = squashed((ROOT / "docs" / "designs/sandbox-design.md").read_text(encoding="utf-8"))
    section = text[text.index("Guards the sandbox makes duplicate") :]

    assert "runtimes/guards.py" in section
    assert "abk policy check" in section
    assert "abk status" in section
