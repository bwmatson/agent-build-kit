"""The documents and the skills describe the requeue a failed unit gets when its wait ends."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
SETTING_DOCUMENTS = (
    ROOT / "docs" / "configuration.md",
    SKILLS / "abk-config" / "SKILL.md",
)
SETTING_IDS = ["configuration.md", "abk-config-skill"]
WAIT_DOCUMENTS = (
    ROOT / "docs" / "cli.md",
    SKILLS / "abk-pipeline" / "SKILL.md",
)
WAIT_IDS = ["cli.md", "abk-pipeline-skill"]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_the_setting_is_named_with_its_four_values_and_its_default(path: Path) -> None:
    text = squashed(path)
    assert "wait_end_requeue" in text
    for value in ("auto", "resume", "rework", "off"):
        assert re.search(rf"wait_end_requeue.{{0,600}}\b{value}\b", text), (
            f"{path.name} lacks {value}"
        )
    assert re.search(r"wait_end_requeue.{0,300}default", text, re.I)


@pytest.mark.parametrize("path", WAIT_DOCUMENTS, ids=WAIT_IDS)
def test_a_failed_unit_is_said_to_be_requeued_once_when_its_wait_ends(path: Path) -> None:
    text = squashed(path)
    assert re.search(r"wait ends.{0,300}requeue|requeue.{0,300}wait ends", text, re.I), path.name
    assert re.search(r"once", text, re.I)


def test_the_cli_document_gives_the_mode_rule_and_the_closed_case() -> None:
    text = squashed(ROOT / "docs" / "cli.md")
    assert "wait_end_requeue" in text
    assert "wait ended: <prerequisite> closed, requeue to retry" in text


def test_the_pipeline_skill_names_the_status_line() -> None:
    text = squashed(SKILLS / "abk-pipeline" / "SKILL.md")
    assert "failed units resumed when their wait ended" in text
    assert "wait ended:" in text


def test_the_architecture_document_no_longer_says_a_waiting_failed_unit_is_never_requeued() -> None:
    text = squashed(ROOT / "docs" / "architecture.md")
    assert "never requeued by the pipeline" not in text


def test_the_architecture_document_names_who_requeues_a_failed_unit() -> None:
    text = squashed(ROOT / "docs" / "architecture.md")
    assert re.search(r"by a person or when its wait ends", text)
