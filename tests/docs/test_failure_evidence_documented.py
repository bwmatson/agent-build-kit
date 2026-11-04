"""The documents, the pipeline skill and the changelog describe the bundle of a failing unit-test
run, the ledger, `abk failures` and the record of load (spec: test-failure-evidence)."""

from __future__ import annotations

from tests.doc_text import ROOT, unreleased_bullets
from tests.prompt_text import flat

SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
CLI = flat((ROOT / "docs" / "cli.md").read_text())
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = flat((ROOT / "docs" / "configuration.md").read_text())
PIPELINE_SKILL = flat((SKILLS / "abk-pipeline" / "SKILL.md").read_text())


def test_the_architecture_describes_the_bundle_of_a_failing_run_beside_the_flake_text() -> None:
    assert "runs/test-failures/" in ARCHITECTURE
    section = ARCHITECTURE[ARCHITECTURE.index("runs/test-failures/") :][:2500]
    for part in ("output.txt", "context.json", "machine.json", "worktree.json", "reruns"):
        assert part in section


def test_the_architecture_says_the_command_reads_the_bundle_and_the_ledger() -> None:
    assert "abk failures" in ARCHITECTURE
    assert "test-runs.jsonl" in ARCHITECTURE[ARCHITECTURE.index("abk failures") :][:2500]


def test_the_cli_reference_has_an_entry_for_the_command_and_its_show_option() -> None:
    entry = CLI[CLI.index("abk failures") :][:2500]
    assert "--show" in entry
    assert "context" in entry and "machine" in entry and "worktree" in entry
    assert "flaky:" in CLI[CLI.index("abk failures") :], "and the status line's load"


def test_the_pipeline_skill_points_at_the_bundle_the_ledger_and_the_command() -> None:
    assert "abk failures" in PIPELINE_SKILL
    assert "runs/test-failures/" in PIPELINE_SKILL


def test_the_documents_describe_the_loaded_flag_and_the_threshold_that_sets_it() -> None:
    assert "load_high" in ARCHITECTURE and "cpus" in ARCHITECTURE
    assert "load_high_per_cpu" in CONFIGURATION
    assert "load_high" in PIPELINE_SKILL


def test_the_changelog_has_a_bullet_for_the_command_and_one_for_the_loaded_flag() -> None:
    bullets = unreleased_bullets()
    assert any("abk failures" in bullet for bullet in bullets)
    assert any("load_high_per_cpu" in bullet for bullet in bullets)
