"""The documents and the changelog describe the three restack points, the lite re-test and
`abk restacks` (spec: restack-points)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CLI = flat((ROOT / "docs" / "cli.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text())
CONFIG_SKILL = flat((SKILLS / "abk-config" / "SKILL.md").read_text())


def test_the_architecture_names_the_three_restack_points() -> None:
    for point in ("`prepare`", "`before_review`", "`before_pr`"):
        assert point in ARCHITECTURE
    assert "before the review" in ARCHITECTURE
    assert "before the pull request" in ARCHITECTURE


def test_the_architecture_says_what_the_lite_path_runs() -> None:
    assert "changelog check" in ARCHITECTURE
    assert "documentation tests" in ARCHITECTURE


def test_the_architecture_says_a_clean_move_before_the_pull_request_starts_no_full_suite() -> None:
    assert "never starts a full suite" in ARCHITECTURE


def test_the_cli_document_describes_the_restacks_command() -> None:
    assert "abk restacks" in CLI
    assert "--since" in CLI[CLI.index("abk restacks") :]


def test_the_restack_check_setting_says_where_full_applies() -> None:
    for text in (CONFIGURATION, CONFIG_SKILL):
        assert "`full` applies at `prepare` and before the review" in text
        assert "never starts the full suite whatever the setting" in text


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any("abk restacks" in bullet for bullet in unreleased_bullets())
