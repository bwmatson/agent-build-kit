"""The documents and the changelog say a confined Claude Code step may reach the host that renews
its login, and that a refused host is logged (spec: claude-steps-can-renew-their-login)."""

from __future__ import annotations

from tests.doc_text import ROOT, squashed, unreleased_bullets

RUNTIMES = ROOT / "docs" / "agent-runtimes.md"
SANDBOX = ROOT / "docs" / "designs" / "sandbox-design.md"


def test_the_runtimes_document_says_a_step_can_renew_its_login_and_a_refusal_is_logged() -> None:
    text = squashed(RUNTIMES.read_text(encoding="utf-8"))
    start = text.index("A confined Claude Code step can renew its own login")
    section = text[start : text.index("## ", start + 10)]

    assert "platform.claude.com" in section and "OAUTH_HOST" in section
    assert "api.anthropic.com, mcp-proxy.anthropic.com and platform.claude.com" in section
    assert "The ACP runtime's list does not gain it" in section
    assert "Proxy(on_refused=...)" in section
    assert "the step reached for <host>, which is not on its allowed list" in section


def test_the_sandbox_design_no_longer_says_two_hosts_were_enough() -> None:
    text = squashed(SANDBOX.read_text(encoding="utf-8"))

    assert "renewing an expired one also needs platform.claude.com" in text


def test_the_changelog_has_a_bullet_for_it() -> None:
    bullets = [b for b in unreleased_bullets() if "renew its own login" in b]

    assert len(bullets) == 1
    assert "platform.claude.com" in bullets[0] and "once per host per step" in bullets[0]
