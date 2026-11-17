"""The documents and the `abk-config` skill describe `repos.<repo>.generated`: its keys, what a
restack does with the paths, the hold cause, and the changelog entry."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


def doc(*parts: str) -> str:
    return flat(ROOT.joinpath(*parts).read_text(encoding="utf-8")).lower()


def unreleased_section() -> str:
    text = ROOT.joinpath("CHANGELOG.md").read_text(encoding="utf-8")
    after = text.split("## Unreleased", 1)[1]
    return flat(after.split("\n## ", 1)[0]).lower()


def test_configuration_documents_the_generated_setting_keys() -> None:
    text = doc("docs", "configuration.md")
    for term in ("generated", "paths", "command", "cwd"):
        assert f"`{term}`" in text


def test_configuration_says_what_a_restack_does_with_generated_files() -> None:
    text = doc("docs", "configuration.md")
    assert "restack" in text
    assert "base" in text
    assert "`generated_files`" in text


def test_configuration_says_a_slash_free_pattern_matches_by_file_name_anywhere() -> None:
    text = doc("docs", "configuration.md")
    assert "slash-free pattern" in text
    assert "file name" in text


def test_the_abk_config_skill_mentions_the_generated_setting() -> None:
    text = flat(skills.source("abk-config")).lower()
    assert "generated:" in text
    assert "cwd" in text


@pytest.mark.parametrize("term", ["generated", "restack", "`generated_files`"])
def test_the_changelog_entry_under_unreleased_covers_the_setting(term: str) -> None:
    assert term in unreleased_section()
