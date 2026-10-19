"""The documents and the skills describe the requeue a failed unit gets when its wait ends."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import LimitsConfig, ProjectLimitsConfig

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


def block(path: Path, key: str) -> str:
    """The example's top-level `key:` block as raw text, up to the next unindented line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{key}:")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()),
        len(lines),
    )
    return "\n".join(lines[start:end])


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_the_setting_sits_in_the_global_limits_example_and_loads(path: Path) -> None:
    assert "wait_end_requeue:" not in block(path, "project_limits")
    loaded = yaml.safe_load(block(path, "global_limits"))["global_limits"]
    assert "wait_end_requeue" in loaded
    assert "wait_end_requeue" not in ProjectLimitsConfig.model_fields
    assert LimitsConfig.model_validate(loaded).wait_end_requeue.value == "auto"


@pytest.mark.parametrize("path", WAIT_DOCUMENTS, ids=WAIT_IDS)
def test_a_failed_unit_is_said_to_be_requeued_once_when_its_wait_ends(path: Path) -> None:
    text = squashed(path)
    assert re.search(
        r"requeued once.{0,200}wait ends|wait ends.{0,200}requeued once", text, re.I
    ), path.name


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
