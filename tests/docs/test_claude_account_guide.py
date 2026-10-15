"""The how-to for a second Claude Code account is in the docs, linked, and accurate
(spec: claude-account)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import AliasChoices

from agent_build_kit import skills
from agent_build_kit.cli import build_parser
from agent_build_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
GUIDE_NAME = "claude-code-second-account.md"
GUIDE = DOCS / GUIDE_NAME
LINKERS = [
    DOCS / "configuration.md",
    DOCS / "agent-runtimes.md",
    Path(skills.SKILLS_DIR) / "abk-config" / "SKILL.md",
]


def guide_text() -> str:
    assert GUIDE.is_file(), f"{GUIDE} does not exist"
    return GUIDE.read_text()


def test_the_guide_exists_and_is_linked_from_the_docs_and_the_skill() -> None:
    guide_text()

    unlinked = [str(path) for path in LINKERS if GUIDE_NAME not in path.read_text()]

    assert unlinked == []


def test_the_guide_names_both_aliases_and_puts_the_value_in_the_env_file_not_abk_yaml() -> None:
    text = guide_text()
    choices = Settings.model_fields["claude_home"].validation_alias
    assert isinstance(choices, AliasChoices)

    for name in choices.choices:
        assert isinstance(name, str) and name in text
    assert ".env" in text
    assert re.search(r"(?:not|never|no)\b[^.\n]*abk\.yaml", text, re.IGNORECASE)


def test_every_abk_command_the_guide_shows_is_a_real_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = set(re.findall(r"\babk ([a-z][a-z-]*)", guide_text()))

    assert {"doctor", "status"} <= shown
    for command in sorted(shown):
        with pytest.raises(SystemExit) as stopped:
            build_parser().parse_args([command, "--help"])
        assert stopped.value.code == 0, f"`abk {command}` is not a subcommand"
    capsys.readouterr()


def test_the_guide_holds_no_real_home_path_and_writes_paths_as_placeholders() -> None:
    text = guide_text()

    assert not re.search(r"/(?:home|Users)/\w+", text)
    assert "$HOME" in text or "<config dir>" in text
