"""The change that fixes a failing or flaky test is written at priority 1, so the fix is not
queued behind the work it blocks (spec: tier2-failures)."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import wait_on_fix
from agent_build_kit.pipeline.untouched_failures import ensure_fix
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked
from tests.untouched_failure_fakes import TEST, failing

FLAKE_TASKS = (
    "# Tasks\n\n"
    "Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.\n\n"
    f"## 1. [app] [unit-test] Make `{TEST}` deterministic\n\n"
    "Priority: 1\n\n"
    "Done when the test passes under load every time, and under the repeat check.\n\n"
    f"- [ ] 1.1 Test: reproduce the race in `{TEST}` deterministically, without "
    "waiting on the clock, so it fails every time before the fix.\n"
    "- [ ] 1.2 Make the test pass: decide whether the test or the code it exercises is "
    "racy, fix that one, and run the test under the repeat check.\n"
)


def test_the_flake_fix_change_is_priority_1_and_no_other_line_changes(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    name = str(wait_on_fix(installation, flaked(TEST), unit))

    assert (installation.changes_dir / name / "tasks.md").read_text() == FLAKE_TASKS


def test_the_pre_existing_fix_change_is_priority_1(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    name = ensure_fix(installation, failing(unit=unit.id), unit, say=lambda line: None)

    text = (installation.changes_dir / name / "tasks.md").read_text()
    assert "\nPriority: 1\n" in text
