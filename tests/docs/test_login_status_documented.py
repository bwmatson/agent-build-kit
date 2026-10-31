"""The documents and the changelog say `abk status` shows each account's login and that a login
refresh row names its account (spec: claude-steps-can-renew-their-login)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed, unreleased_bullets

CLI = ROOT / "docs" / "cli.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"


def test_the_cli_document_describes_the_login_line() -> None:
    text = squashed(CLI.read_text(encoding="utf-8"))
    start = text.index("status prints a login: line")
    paragraph = text[start : start + 900]

    assert "token expires 06:00Z (in 4h47m)" in paragraph
    assert "token expired 12m ago" in paragraph
    assert "last real usage read 89m ago" in paragraph
    assert "no real usage read yet" in paragraph
    assert "makes no call" in paragraph


def test_the_skill_names_the_login_line_among_what_status_shows() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))

    assert "a login: line: when its token expires or that it has" in text


def test_the_changelog_says_the_ledger_row_names_its_account() -> None:
    bullets = [b for b in unreleased_bullets() if "login_refresh" in b]

    assert len(bullets) == 1
    assert "names the account it refreshed" in bullets[0] and "login: line" in bullets[0]
