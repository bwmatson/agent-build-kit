"""The documents and the changelog describe the sweep of `unplanned` units and `abk units prune`
(spec: unplanned-sweep)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

CLI = flat((ROOT / "docs" / "cli.md").read_text())
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())


def test_the_cli_document_describes_the_command() -> None:
    assert "abk units prune --unplanned [--dry-run]" in CLI
    assert "first condition" in CLI


def test_the_cli_document_says_an_archived_change_keeps_what_no_live_unit_carries() -> None:
    assert "an archived change keeps a unit whose groups no live unit carries" in CLI
    assert "exit 1 when there are `unplanned` units and no changes folder" in CLI


def test_the_architecture_says_a_tombstone_is_kept_one_pass_then_swept() -> None:
    assert "kept for one pass" in ARCHITECTURE
    assert "removes it once it holds no work" in ARCHITECTURE
    assert "an archived change keeps a unit whose groups no live unit carries" in ARCHITECTURE


def test_the_architecture_says_a_swept_id_may_be_reused() -> None:
    assert "id may be reused by a later plan" in ARCHITECTURE


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "abk units prune" in bullet and "unplanned" in bullet for bullet in unreleased_bullets()
    )
