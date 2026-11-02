"""The documents, the `abk-pipeline` skill and the changelog describe the regression agent: the
order of checks a failing test goes through, the unit's base, the agent, the full review and the
naming (spec: regression-agent)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
RUNTIMES = flat((ROOT / "docs" / "agent-runtimes.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text())
CLI = flat((ROOT / "docs" / "cli.md").read_text())
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)

FLAKE = ARCHITECTURE[ARCHITECTURE.index("**A flake is isolated, recorded and fixed once.**") :]
FLAKE = FLAKE.split("**A pre-existing failure is recorded and fixed once.**", 1)[0]
PREEXISTING = ARCHITECTURE[
    ARCHITECTURE.index("**A pre-existing failure is recorded and fixed once.**") :
]
PREEXISTING = PREEXISTING.split(" - **", 1)[0]


def test_the_architecture_gives_the_order_of_checks() -> None:
    assert "An open fix for the failing test is waited on first" in ARCHITECTURE
    assert "before any rerun" in ARCHITECTURE
    assert "also after a requeue" in ARCHITECTURE


def test_the_architecture_describes_the_unit_test_base_check() -> None:
    assert "unit-test base check" in ARCHITECTURE
    assert "a test the unit wrote is not run on the base" in ARCHITECTURE
    assert "the branch tip of its parent when it is stacked" in ARCHITECTURE
    assert "passing there leaves the failure the unit's" in ARCHITECTURE


def test_the_flake_section_says_the_regression_agent_writes_a_full_review_change() -> None:
    assert "full review" in FLAKE
    assert "[contract]" in FLAKE
    assert "`fix-test-<slug>` (a long name is cut and takes a hash)" in FLAKE
    assert "covers every failed test" in ARCHITECTURE
    assert "covers every failed test" in SKILL
    assert "rewritten once" in FLAKE


def test_the_pre_existing_section_says_the_agent_judges_and_the_change_is_reviewed_in_full() -> (
    None
):
    assert "full review" in PREEXISTING
    assert "whether the test or the implementation is wrong" in PREEXISTING
    assert "unit-test failure that fails on the base" in PREEXISTING


def test_the_architecture_says_a_timeout_that_fails_alone_waits_for_its_fix() -> None:
    assert "fails by its time limit" in ARCHITECTURE
    assert "fails again by itself" in ARCHITECTURE


def test_the_runtimes_document_names_the_regression_role_and_its_model() -> None:
    assert "`regression` role" in RUNTIMES
    assert "`regression` defaults to Opus" in RUNTIMES
    assert "ABK_REGRESSION_MODEL" in RUNTIMES


def test_the_configuration_document_names_the_role_and_the_cap() -> None:
    assert "`regression` role" in CONFIGURATION
    models = CONFIGURATION[CONFIGURATION.index("regression: opus") :][:300]
    assert "fix change" in models
    cap = CONFIGURATION[CONFIGURATION.index("max_regression_runs_per_hour") :][:400]
    assert "one run" in cap, "a storm of failures of one test costs one run"


def test_the_cli_document_names_the_change_and_the_judgement() -> None:
    status = CLI[CLI.index("a `pre-existing:` line") :][:600]
    assert "judgement" in status
    assert "`fix-test-" in status
    assert "abk explain" in CLI[CLI.index("regression agent") :]


def test_the_pipeline_skill_describes_the_agent_and_no_longer_a_template() -> None:
    assert "written without a model" not in SKILL
    assert "regression agent" in SKILL
    assert "full review" in SKILL
    assert "unit's base" in SKILL
    assert "An open fix for the failing test is waited on first" in SKILL


def test_the_changelog_has_one_bullet_for_the_agent() -> None:
    bullets = [b for b in unreleased_bullets() if "regression agent writes" in b]
    assert len(bullets) == 1
    assert "fix-test-" in bullets[0]
    assert "full review" in bullets[0]
