"""The documents say how a scratch tick treats usage."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRST_LINE = "usage guard off (ABK_USAGE_GUARD)"


def unreleased() -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    return re.split(r"^## ", changelog, flags=re.MULTILINE)[1]


def test_configuration_names_the_setting_its_two_values_and_that_it_is_not_a_yaml_key() -> None:
    text = (ROOT / "docs" / "configuration.md").read_text()

    assert "ABK_USAGE_GUARD" in text
    row = next(line for line in text.splitlines() if "ABK_USAGE_GUARD" in line)
    assert "`on`" in row
    assert "`off`" in row
    assert re.search(r"not an `abk\.yaml` key|never .*`abk\.yaml`", text)


def test_the_cli_document_shows_the_ticks_first_line() -> None:
    text = (ROOT / "docs" / "cli.md").read_text()

    assert FIRST_LINE in text


def test_the_pipeline_skill_says_a_live_test_skips_on_a_usage_pause_and_why() -> None:
    text = (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()

    assert "environment condition" in text
    assert re.search(r"live test.{0,200}skip", text, re.IGNORECASE | re.DOTALL)


def test_the_changelog_entry_says_a_usage_condition_skips_a_live_test() -> None:
    entry = next(b for b in unreleased().split("\n\n") if "ABK_USAGE_GUARD" in b)
    assert re.search(r"skip", entry, re.IGNORECASE), entry
