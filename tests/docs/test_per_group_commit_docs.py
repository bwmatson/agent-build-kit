"""The documents and the skills describe stubs, the check-and-fix loop and per-group commits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCS = ROOT / "docs"
SETTING_DOCUMENTS = (DOCS / "configuration.md", SKILLS / "abk-config" / "SKILL.md")
SETTING_IDS = ["configuration.md", "abk-config-skill"]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def gate_section(path: Path) -> str:
    """The `abk gate` section of the CLI document, squashed."""
    text = path.read_text(encoding="utf-8")
    start = text.index("### `abk gate")
    end = text.find("\n### ", start + 1)
    return " ".join(text[start : end if end != -1 else None].replace("`", "").split())


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_the_setting_is_named_with_its_default_and_what_it_does(path: Path) -> None:
    text = squashed(path)
    assert "builders.stubbed_tdd_commits" in text
    assert re.search(r"stubbed_tdd_commits.{0,600}default", text, re.I)
    assert re.search(r"stubbed_tdd_commits.{0,800}\bstubs?\b", text, re.I)
    assert re.search(r"stubbed_tdd_commits.{0,800}\bgroups?\b", text, re.I)


def test_the_unit_graph_names_both_new_steps() -> None:
    text = squashed(DOCS / "unit-graph.md")
    assert "stub_checks" in text
    assert "fix_stub_checks" in text


def test_the_toolchain_profiles_document_names_the_stub_declarations() -> None:
    text = squashed(DOCS / "toolchain-profiles.md")
    assert "supports_stubs" in text
    assert re.search(r"clean_command.{0,300}types", text, re.I)
    assert re.search(r"stubbed.{0,300}(red|JUnit|Vitest)", text, re.I)


def test_the_cli_document_describes_the_gates_paired_and_types_checks() -> None:
    text = gate_section(DOCS / "cli.md")
    assert re.search(r"\bpaired\b", text, re.I)
    assert re.search(r"\btypes?\b", text, re.I)
    assert "stubbed_tdd_commits" in text


def test_the_pipeline_skill_names_the_feedback_source_and_the_requeue() -> None:
    text = squashed(SKILLS / "abk-pipeline" / "SKILL.md")
    assert "stub-checks" in text
    assert re.search(r"stub-checks.{0,600}requeue", text, re.I)
    assert re.search(r"stub-checks.{0,800}\btests?\b", text, re.I)


def test_the_architecture_document_describes_the_stubbed_build() -> None:
    text = squashed(DOCS / "architecture.md")
    assert "stub_checks" in text
    assert "fix_stub_checks" in text
    assert "stubbed_tdd_commits" in text
