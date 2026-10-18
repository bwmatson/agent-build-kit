"""The documents, the skills and the changelog describe the agent commands (spec:
toolchain-profiles, build-prompts)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
PROFILES = (ROOT / "docs" / "toolchain-profiles.md").read_text()
CONFIGURATION = (ROOT / "docs" / "configuration.md").read_text()
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"


def unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    start = text.index("## Unreleased")
    return text[start:].split("\n## ", 1)[0]


def test_the_profiles_document_has_the_protocol_row_and_the_allow_list_rule() -> None:
    assert re.search(r"^\| `agent_commands`", PROFILES, re.MULTILINE)
    assert re.search(r"agent_commands[^.]*allow-list|allow-list[^.]*agent_commands", flat(PROFILES))


def test_the_configuration_document_shows_the_key_and_the_doctor_row() -> None:
    assert re.search(r"^\s+agent_commands:", CONFIGURATION, re.MULTILINE)
    assert re.search(r"^\| agent commands", CONFIGURATION, re.MULTILINE)


def test_the_config_and_pipeline_skills_mention_the_key() -> None:
    for skill in ("abk-config", "abk-pipeline"):
        assert "agent_commands" in (SKILLS / skill / "SKILL.md").read_text(), skill


def test_the_changelog_has_a_bullet_under_unreleased_naming_the_key() -> None:
    bullets = [b for b in unreleased().split("\n\n") if b.startswith("- ")]

    assert any("agent_commands" in bullet for bullet in bullets)
