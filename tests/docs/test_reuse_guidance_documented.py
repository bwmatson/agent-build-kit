"""The documents describe the two reuse guidance versions and which prompts carry them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"


def squashed(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def reuse_section() -> str:
    text = squashed(ROOT / "docs" / "architecture.md")
    start = text.index("Builders are told to reuse before they write")
    return text[start : start + 5000]


def test_the_architecture_document_names_the_two_versions_and_their_templates() -> None:
    section = reuse_section()

    assert "reuse-guidance-tests.md" in section
    assert re.search(r"source version", section, re.I)
    assert re.search(r"test version", section, re.I)


def test_the_architecture_document_says_which_prompts_carry_which_version() -> None:
    section = reuse_section()

    assert re.search(r"source version.{0,200}implement.{0,100}fix", section, re.I)
    assert re.search(r"test version.{0,200}tests (step|prompt)", section, re.I)
    assert re.search(r"rework.{0,200}(both|test version).{0,120}test file", section, re.I)
    assert re.search(r"continuation.{0,100}neither", section, re.I)


def test_the_architecture_document_names_the_test_points() -> None:
    section = reuse_section()

    for point in ("T8a", "T21", "T22"):
        assert point in section
    assert re.search(r"parametri[sz]e", section, re.I)


def test_the_architecture_document_says_the_placement_rule_is_stated_once() -> None:
    section = reuse_section()

    assert re.search(r"placement rule.{0,200}(stated once|once).{0,120}tests prompt", section, re.I)


def test_the_authoring_skill_does_not_repeat_the_old_single_block() -> None:
    assert "reuse-guidance-tests.md" in reuse_section()
    for skill in SKILLS.glob("*/SKILL.md"):
        assert "Reuse before you write" not in skill.read_text(encoding="utf-8")
