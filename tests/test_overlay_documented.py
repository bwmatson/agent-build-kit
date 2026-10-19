"""`abk.local.yaml` is documented, listed in the init template's `.gitignore` and `.env.example`,
and the second-account document describes the in-repo form (spec: claude-accounts, the overlay
is documented and kept out of git)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "agent_build_kit" / "templates"
CONFIGURATION = ROOT / "docs" / "configuration.md"
SECOND_ACCOUNT = ROOT / "docs" / "claude-code-second-account.md"
OVERLAY = "abk.local.yaml"


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_the_init_template_ignores_the_overlay_and_the_env_example_names_it() -> None:
    ignored = (TEMPLATES / "gitignore").read_text().splitlines()

    assert OVERLAY in ignored
    assert OVERLAY in (TEMPLATES / "env.example").read_text()


def test_the_configuration_document_shows_an_account_directory_in_the_overlay() -> None:
    text = squashed(CONFIGURATION)

    assert "accounts:" in text
    assert "config_dir" in text
    assert "repos.<name>.account" in text


def test_the_second_account_document_describes_the_in_repo_form() -> None:
    text = squashed(SECOND_ACCOUNT)

    assert "repos.<name>.account" in text
    assert "accounts.<label>" in text
    assert OVERLAY in text
    assert "abk.yaml" in text


def test_the_second_account_document_says_what_a_person_with_one_account_gets() -> None:
    text = squashed(SECOND_ACCOUNT).lower()

    assert "one account" in text
    assert "default account" in text
    assert "falls back" in text or "fallback" in text


def test_the_second_account_document_keeps_the_per_installation_env_form_as_the_alternative() -> (
    None
):
    text = squashed(SECOND_ACCOUNT)

    assert "CLAUDE_CONFIG_DIR" in text
    assert ".env" in text
    assert "alternative" in text.lower()
