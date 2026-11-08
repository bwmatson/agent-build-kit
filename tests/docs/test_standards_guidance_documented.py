"""The architecture document says how the test standards reach the builders and the reviewer
(spec: standards-in-prompts-now)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed


def test_the_architecture_document_describes_the_standards_table_and_checklist() -> None:
    text = squashed((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))

    assert "table of the test standards once per session" in text
    assert "checklist of the judgements a program cannot make" in text
    assert "generated catalogue replaces the hand-written table" in text
