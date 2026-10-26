"""The documents say what the login refresh does and that every account uses one path
(spec: login-refresh)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SECOND_ACCOUNT = DOCS / "claude-code-second-account.md"
ARCHITECTURE = DOCS / "architecture.md"
CONFIGURATION = DOCS / "configuration.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def section(path: Path, heading: str) -> str:
    """The text under the heading naming `heading`, to the next heading of its level or above."""
    text = path.read_text()
    match = re.search(rf"^(#+) .*{re.escape(heading)}.*$", text, re.M | re.I)
    assert match, f"{path.name} has no heading naming {heading}"
    rest = text[match.end() :]
    following = re.search(rf"^#{{1,{len(match[1])}}} ", rest, re.M)
    return " ".join((rest[: following.start()] if following else rest).split())


def test_the_second_account_document_has_a_login_refresh_paragraph() -> None:
    text = section(SECOND_ACCOUNT, "login refresh")

    assert "CLAUDE_CONFIG_DIR" in text, "it does not say the refresh runs under the directory"
    assert "401" in text and "rejected" in text, "it does not say what a 401 after it means"
    assert "claude auth login" in text
    assert re.search(r"how to tell|you can tell|it worked|worked", text), "no sign it worked"


def test_the_architecture_says_every_account_uses_one_path_and_names_the_files() -> None:
    text = squashed(ARCHITECTURE)

    assert re.search(r"every account (uses|goes through|runs through) one path", text)
    assert "usage-cache.<label>.json" in text


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL], ids=lambda p: p.name)
def test_the_configuration_and_the_skill_say_the_same(path: Path) -> None:
    text = squashed(path)

    assert re.search(r"every account (uses|goes through|runs through) one path", text)
    assert re.search(r"CLAUDE_CODE_OAUTH_TOKEN[^.]*(precedence|first|before)", text)


def test_the_changelog_has_a_bullet_for_the_rejected_login() -> None:
    text = CHANGELOG.read_text()
    start = text.index("## Unreleased")
    following = re.search(r"^## ", text[start + 2 :], re.M)
    body = text[start : start + 2 + following.start()] if following else text[start:]

    assert re.search(r"login is rejected|rejected login", body)
