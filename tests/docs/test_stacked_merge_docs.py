"""The guides say how a stack merged at once is read, what `landing_wait` and `landing_unknown`
mean, and the changelog carries the entry (spec: stacked-merges-land-on-the-default-branch)."""

from __future__ import annotations

import pytest

from tests.doc_text import ROOT, squashed, unreleased_bullets

ARCHITECTURE = squashed((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = squashed((ROOT / "docs" / "configuration.md").read_text())
SKILL = squashed(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def test_the_architecture_says_each_pull_request_of_a_stack_merged_at_once_is_read_alone() -> None:
    assert "merged at once" in ARCHITECTURE
    assert "its own commit" in ARCHITECTURE


def test_the_architecture_says_a_reported_commit_counts_only_when_on_the_default_branch() -> None:
    assert "a commit the host reports counts only when it is on the default branch" in ARCHITECTURE


def test_the_architecture_says_a_unit_with_no_commit_waits_for_landing_wait() -> None:
    assert ARCHITECTURE.count("landing_wait") >= 2
    assert ARCHITECTURE.count("landing_unknown") >= 2


def test_the_configuration_says_landing_wait_applies_to_a_stack_merged_at_once() -> None:
    assert "merged at once" in CONFIGURATION


@pytest.mark.parametrize("term", ["landing_wait", "landing_unknown"])
def test_the_pipeline_skill_mentions_the_term(term: str) -> None:
    assert term in SKILL


def test_the_changelog_has_an_entry_for_a_stack_merged_at_once_under_unreleased() -> None:
    assert any("merged at once" in b and "landing_wait" in b for b in unreleased_bullets())
