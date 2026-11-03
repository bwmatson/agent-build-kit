"""The documents, the skills and the changelog describe the affected-tests command of the python-uv
agent defaults and its risk (spec: agent-test-commands)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text().replace("# ", ""))
PIPELINE = flat((SKILLS / "abk-pipeline" / "SKILL.md").read_text())
CONFIG_SKILL = flat((SKILLS / "abk-config" / "SKILL.md").read_text().replace("# ", ""))


def test_the_configuration_and_the_config_skill_list_the_affected_scope() -> None:
    assert "whole|file|node-id|affected" in CONFIGURATION
    assert "whole|file|node-id|affected" in CONFIG_SKILL


def test_the_architecture_and_the_pipeline_skill_state_the_no_data_risk() -> None:
    for text in (ARCHITECTURE, PIPELINE):
        assert "scope `affected`" in text
        assert "runs the whole suite" in text


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "scope affected" in bullet and "pytest-testmon" in bullet for bullet in unreleased_bullets()
    )
