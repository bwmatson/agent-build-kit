"""The authoring skill and the documents say the program names a unit from its lowest group
(spec: unit-ids-come-from-the-groups)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


def text_of(name: str) -> str:
    return flat((ROOT / "docs" / name).read_text()).lower()


def test_the_authoring_skill_says_the_program_names_units_and_they_can_be_predicted() -> None:
    text = flat(skills.source("abk-authoring")).lower()

    assert re.search(r"program (names|assigns)[^.]*unit", text)
    assert "<change>/<lowest group>" in text


def test_the_architecture_doc_names_the_labels_and_the_reuse() -> None:
    text = text_of("architecture.md")

    assert "id (<change>/<n>)" not in text
    assert re.search(r"label", text)
    assert re.search(r"<change>/<lowest group>", text)
    assert re.search(r"reuse[^.]*(unstarted|same groups)", text)


def test_the_unit_graph_doc_says_how_an_id_is_formed_and_when_it_is_fixed() -> None:
    text = text_of("designs/unit-graph.md")

    assert "<change>/<lowest group>" in text
    assert re.search(r"(never changes|never changed|fixed)[^.]*(start|first plan)", text)
