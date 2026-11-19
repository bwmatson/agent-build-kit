"""The docs and the `abk-pipeline` skill describe the content check, the carry, `abk carry` and
`delete_merged_branches` (spec: landed-carry)."""

from __future__ import annotations

import re

import pytest

from tests.doc_text import ROOT
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text())
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def whole(phrase: str, text: str) -> bool:
    """Whether `phrase` is in `text` as whole words, so "the carry" misses "the carrying"."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


@pytest.mark.parametrize(
    "phrase",
    ["the content check", "the carry", "`abk carry`", "`delete_merged_branches`"],
)
def test_the_pipeline_guide_describes_the_carry_and_its_setting(phrase: str) -> None:
    assert whole(phrase, ARCHITECTURE)


def test_the_pipeline_guide_says_the_content_check_looks_for_changes_on_the_default_branch() -> (
    None
):
    index = ARCHITECTURE.find("the content check")
    assert index != -1, "the pipeline guide does not describe the content check"
    assert "default branch" in ARCHITECTURE[index : index + 600]


def test_the_configuration_guide_ties_the_branch_deletion_setting_to_the_restack() -> None:
    index = CONFIGURATION.find("delete_merged_branches")
    assert index != -1, "the configuration guide does not document the setting"
    assert "refs/abk/bases/" in CONFIGURATION[index : index + 600]


def test_the_changelog_names_the_carry_and_doctor_under_unreleased() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    start = changelog.index("## Unreleased")
    unreleased = changelog[start + len("## Unreleased") :].split("\n## ", 1)[0]
    assert "`abk carry`" in unreleased
    assert "`abk doctor`" in unreleased


def test_the_skill_mentions_the_carry() -> None:
    assert whole("the carry", SKILL)
    assert "`abk carry`" in SKILL
