"""The documents, the `abk-pipeline` skill and the changelog describe the login pause (spec:
login-pause): what a rejected login does to an account's units, how it ends and what status
shows."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CLI = flat((ROOT / "docs" / "cli.md").read_text())
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def test_the_architecture_says_how_a_rejected_login_pauses_and_ends() -> None:
    assert "A rejected Claude login pauses the account's units" in ARCHITECTURE
    assert "runs the CLI's logged-in probe once" in ARCHITECTURE
    assert "admits no unit that has never started" in ARCHITECTURE


def test_the_cli_document_says_what_status_shows() -> None:
    assert "units paused for the login" in CLI


def test_the_skill_says_how_to_read_it() -> None:
    assert "### Paused for a rejected login" in SKILL
    assert "Nothing needs requeuing" in SKILL


def test_the_changelog_has_a_bullet() -> None:
    assert any(
        "rejected Claude login" in bullet and "pauses the account's units" in bullet
        for bullet in unreleased_bullets()
    )
