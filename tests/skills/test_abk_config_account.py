"""The packaged `abk-config` skill states the account setting as the settings layer has it
(spec: claude-account)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import AliasChoices

from agent_build_kit import skills
from agent_build_kit.settings import Settings

# What reads as one of the account's variable names: `<PREFIX>_CLAUDE_<WORD>`, `CLAUDE_CONFIG<...>`.
NAME = re.compile(r"\b(?:[A-Z]+_CLAUDE_[A-Z_]+|CLAUDE_CONFIG[A-Z_]*)\b")


def skill_text() -> str:
    return (Path(skills.SKILLS_DIR) / "abk-config" / "SKILL.md").read_text()


def test_the_skill_names_both_settings_and_says_the_account_is_not_in_abk_yaml() -> None:
    text = skill_text()
    choices = Settings.model_fields["claude_home"].validation_alias
    assert isinstance(choices, AliasChoices)

    listed = set(NAME.findall(text))

    assert listed == {name for name in choices.choices if isinstance(name, str)}
    assert re.search(r"(?:not|never|no)\b[^.\n]*abk\.yaml", text, re.IGNORECASE)
    assert ".env" in text


def test_the_skill_names_abk_doctor_as_the_place_that_says_where_the_value_came_from() -> None:
    text = skill_text()

    assert re.search(r"abk doctor[^.\n]*(?:from|source|came)", text, re.IGNORECASE) or re.search(
        r"(?:from|source|came)[^.\n]*abk doctor", text, re.IGNORECASE
    )
