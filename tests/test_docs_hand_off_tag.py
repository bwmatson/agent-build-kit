"""The hand-off tag is `handoff`, without the `abk` prefix (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

HAND_OFF = Path(__file__).resolve().parent.parent / "docs" / "hand-off.md"


def test_the_document_names_the_tag_handoff_and_not_the_prefixed_name() -> None:
    text = HAND_OFF.read_text()

    assert "`handoff`" in text
    assert "abk-handoff" not in text
