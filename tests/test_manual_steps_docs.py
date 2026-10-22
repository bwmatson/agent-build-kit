"""The documents and the skills describe the manual steps (spec: manual-steps)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DECLARING = (
    ROOT / "docs" / "cli.md",
    ROOT / "docs" / "unit-graph.md",
    SKILLS / "abk-authoring" / "SKILL.md",
)
DECLARING_IDS = ["cli.md", "unit-graph.md", "abk-authoring-skill"]


def text(path: Path) -> str:
    return flat(path.read_text(encoding="utf-8").replace("`", ""))


@pytest.mark.parametrize("path", DECLARING, ids=DECLARING_IDS)
def test_when_to_declare_a_manual_step_is_given_with_its_runbook(path: Path) -> None:
    said = text(path)
    assert "Manual:" in said, path.name
    assert re.search(r"only a person can do", said, re.I), path.name
    assert re.search(r"Manual:.{0,600}runbook|runbook.{0,600}Manual:", said, re.I), path.name


def test_the_cli_document_lists_the_manual_commands() -> None:
    said = text(ROOT / "docs" / "cli.md")
    for command in ("abk manual list", "abk manual raise", "abk manual check"):
        assert command in said, command


def test_the_pipeline_skill_says_what_waiting_for_a_manual_step_means() -> None:
    said = text(SKILLS / "abk-pipeline" / "SKILL.md")
    assert "waiting for manual step" in said
    assert re.search(r"waiting for manual step.{0,600}abk manual list", said, re.I | re.S)


def test_the_needs_a_human_table_names_a_raised_manual_step_for_a_builder_limit() -> None:
    body = (SKILLS / "abk-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    section = body.split('## Why a unit is held "needs a human"', 1)[1].split("\n## ", 1)[0]
    assert re.search(r"abk manual raise", flat(section))
