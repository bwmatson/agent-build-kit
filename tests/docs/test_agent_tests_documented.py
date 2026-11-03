"""The documents, the `abk-pipeline` skill and the changelog say that build agents are not given a
whole-suite test command by default and are told to run their own tests (spec:
agent-test-commands)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text().replace("# ", ""))
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def test_the_architecture_says_a_build_agent_runs_its_own_tests() -> None:
    assert "A build agent runs its own tests" in ARCHITECTURE
    assert "no whole-suite test command" in ARCHITECTURE
    assert "127.0.0.1" in ARCHITECTURE


def test_the_configuration_says_the_defaults_name_no_whole_suite_command() -> None:
    assert "no command that runs the whole suite" in CONFIGURATION


def test_the_skill_says_what_a_whole_suite_run_in_an_agent_log_means() -> None:
    assert "no command that runs the whole suite" in SKILL
    assert "whole-suite `pytest` run" in SKILL


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "whole test suite" in bullet and "agent_commands" in bullet
        for bullet in unreleased_bullets()
    )
