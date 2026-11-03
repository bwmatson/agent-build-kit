"""The architecture document, the `abk-pipeline` skill and the changelog say that a unit-test run
that reaches the command's time limit holds its unit for a person (spec:
unit-test-command-limit)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def test_the_architecture_says_a_timed_out_run_holds_the_unit_and_runs_no_fix_agent() -> None:
    assert "holds the unit for a person" in ARCHITECTURE
    assert "runs no fix agent" in ARCHITECTURE


def test_the_skill_says_how_to_read_and_release_the_hold() -> None:
    assert "A unit-test timeout" in SKILL
    assert "`abk requeue`" in SKILL


def test_the_changelog_has_a_bullet_for_it() -> None:
    assert any(
        "time limit" in bullet and "holds its unit" in bullet for bullet in unreleased_bullets()
    )
