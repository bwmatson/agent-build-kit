"""The documents, the skills and the changelog say how to limit whole-suite unit-test runs (spec:
unit-test-concurrency): where the setting belongs, what the doctor says of it, what a waiting
unit's log line and `abk status` show, and that the wait is outside the command's time limit."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text().replace("# ", ""))
CLI = flat((ROOT / "docs" / "cli.md").read_text())
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIG_SKILL = flat((SKILLS / "abk-config" / "SKILL.md").read_text().replace("# ", ""))
PIPELINE_SKILL = flat((SKILLS / "abk-pipeline" / "SKILL.md").read_text())


def test_the_configuration_lists_the_setting_and_puts_it_in_the_local_file() -> None:
    assert "max_concurrent_unit_tests:" in CONFIGURATION
    assert re.search(
        r"`global_limits\.max_concurrent_unit_tests`[^|]*\|\s*`abk\.local\.yaml`", CONFIGURATION
    )


def test_the_config_skill_lists_it_among_what_the_local_file_holds() -> None:
    assert "global_limits.max_concurrent_unit_tests" in CONFIG_SKILL
    assert re.search(r"abk\.local\.yaml`?\*\*:[^-]*max_concurrent_unit_tests", CONFIG_SKILL)


def test_the_doctor_table_lists_the_three_results() -> None:
    assert "| unit-test slots |" in CLI
    for phrase in ("not limited", "above", "abk.local.yaml"):
        assert phrase in CLI[CLI.index("| unit-test slots |") :][:900]


def test_the_status_section_describes_the_slot_line() -> None:
    assert "unit-test slots (N at once)" in CLI
    assert "waiting:" in CLI


def test_the_architecture_says_the_wait_is_outside_the_commands_time_limit() -> None:
    assert "waits for a free slot" in ARCHITECTURE
    assert "outside the command's time limit" in ARCHITECTURE
    assert "abk status" in ARCHITECTURE[ARCHITECTURE.index("waits for a free slot") :][:1200]


def test_the_pipeline_skill_says_what_the_waiting_log_line_means() -> None:
    assert "waiting for a unit-test slot" in PIPELINE_SKILL
    assert "wait_seconds" in PIPELINE_SKILL


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "max_concurrent_unit_tests" in bullet and "abk.local.yaml" in bullet
        for bullet in unreleased_bullets()
    )
