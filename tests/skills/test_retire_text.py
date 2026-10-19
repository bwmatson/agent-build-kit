"""The skills, the documents and the changelog say what retiring a unit is, how to leave a bad
spot and that a replan keeps a started unit (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
FLAGS = ("--reason", "--delete-branch", "--discard-unpushed", "--dry-run")


def blocks(text: str) -> list[str]:
    """The paragraphs of `text`, squeezed and lowercased."""
    return [flat(block).lower() for block in re.split(r"\n\s*\n", text)]


def document(name: str) -> list[str]:
    return blocks((ROOT / "docs" / name).read_text(encoding="utf-8"))


def test_the_pipeline_skill_names_the_command_and_the_state_it_sets() -> None:
    found = [b for b in blocks(skills.source("abk-pipeline")) if "abk retire" in b]

    assert any("retired" in block for block in found)


def test_the_pipeline_skill_names_the_kept_line_of_a_replan() -> None:
    found = [b for b in blocks(skills.source("abk-pipeline")) if "kept:" in b]

    assert any("not in the plan" in block and "abk retire" in block for block in found)


def test_the_pipeline_skill_says_a_plan_giving_a_group_to_a_second_unit_is_refused() -> None:
    found = [b for b in blocks(skills.source("abk-pipeline")) if "abk retire" in b]

    assert any(
        "refus" in block and re.search(r"(second|another|two) unit", block) for block in found
    )


def test_the_authoring_skill_says_a_group_has_one_owner_and_how_to_move_it() -> None:
    found = [b for b in blocks(skills.source("abk-authoring")) if "abk retire" in b]

    assert any("group" in block and ("owner" in block or "one unit" in block) for block in found), (
        "no paragraph says a group's owner is one unit and that retiring it moves the group"
    )


def test_the_command_reference_names_the_command_its_flags_and_the_state() -> None:
    found = [b for b in document("cli.md") if "abk retire" in b]
    text = " ".join(found)

    assert found
    for flag in FLAGS:
        assert flag in text, f"cli.md does not describe {flag} of abk retire"
    assert "retired" in text


def test_the_unit_graph_document_lists_retired_among_the_states_with_the_command() -> None:
    found = [b for b in document("unit-graph.md") if "abk retire" in b]

    assert any("retired" in block for block in found)


def test_the_architecture_document_gives_the_demotion_and_ownership_rules() -> None:
    found = [b for b in document("architecture.md") if "abk retire" in b]

    assert any("owner" in block or "one unit" in block for block in found)


def test_the_changelog_has_a_bullet_for_the_command() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]

    assert "abk retire" in flat(section)
