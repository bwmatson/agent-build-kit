"""The architecture document describes the work tracker; the hand-off document drops "interim"."""

from __future__ import annotations

from pathlib import Path

from tests.live_tag_drift import section_of

ROOT = Path(__file__).resolve().parents[2]


def test_the_architecture_document_has_a_work_tracker_section_naming_its_parts() -> None:
    section = section_of(ROOT / "docs" / "architecture.md", "## Work tracker")
    lowered = section.lower()
    missing = [
        term for term in ("reconciler", "wanted board", "manual parent") if term not in lowered
    ]
    if "Epic" not in section:
        missing.append("Epic")
    assert missing == [], f"the work-tracker section does not name: {missing}"


def test_the_hand_off_document_does_not_call_the_hold_interim() -> None:
    text = (ROOT / "docs" / "hand-off.md").read_text(encoding="utf-8")
    assert "interim" not in text.lower()
