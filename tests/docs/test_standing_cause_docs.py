"""The architecture and unit-graph documents define standing and event causes, and the carry."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import EVENT_CAUSES, STANDING_CAUSES, Cause
from tests.prompt_text import flat

DOCS = Path(__file__).resolve().parents[2] / "docs"
NAMES = ["architecture.md", "designs/unit-graph.md"]


def text_of(name: str) -> str:
    return flat((DOCS / name).read_text(encoding="utf-8"))


def definition(name: str) -> str:
    """The paragraph (not a table row) that names both kinds of cause."""
    blocks = re.split(r"\n\s*\n", (DOCS / name).read_text(encoding="utf-8"))
    found = [
        flat(block)
        for block in blocks
        if not block.lstrip().startswith("|")
        and "standing cause" in block.lower()
        and "event cause" in block.lower()
    ]
    assert found, f"{name} has no paragraph defining standing and event causes"
    return found[0]


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.;])\s+", text.lower())


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("cause", sorted(STANDING_CAUSES | EVENT_CAUSES))
def test_the_definition_names_every_cause_exactly_once(name: str, cause: Cause) -> None:
    assert definition(name).count(f"`{cause.value}`") == 1


@pytest.mark.parametrize("name", NAMES)
def test_the_document_says_a_replan_carries_a_standing_cause_and_an_event_ends_it(
    name: str,
) -> None:
    found = sentences(text_of(name))

    assert any("replan" in s and "carries" in s and "standing cause" in s for s in found)
    assert any("event cause" in s and "ends" in s and "standing" in s for s in found)
    assert any("no cause" in s and "before causes" in s and "event" in s for s in found)
    assert any("upsert" in s and "keeps" in s and "runtime fields" in s for s in found)


def test_the_architecture_document_no_longer_reads_the_cause_as_the_latest_entrys() -> None:
    text = text_of("architecture.md").lower()

    assert "its last cause" not in text
    assert not re.search(r"cause[^.]*\b(latest|last) (history )?entry", text)


def test_the_architecture_document_names_the_carried_mark_and_cause_since() -> None:
    text = text_of("architecture.md")

    assert "`carried`" in text
    assert "`cause_since`" in text
