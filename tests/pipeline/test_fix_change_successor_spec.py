"""A successor change restates a requirement only when the shipped spec holds it: an archived
fix of the other kind added a different requirement to a different capability (spec:
regression-agent)."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import CAPABILITY, fix_change_name, wait_on_fix
from tests.pipeline.test_flake_fix_change import TEST, change_with_unit, code_repo, flaked
from tests.pipeline.test_untouched_failures_change import ensured
from tests.untouched_failure_fakes import TEST as FAILING_TEST


def archive(inst: Installation, test: str, prefix: str) -> None:
    name = fix_change_name(test, prefix)
    (inst.changes_dir / "archive" / f"2026-03-01-{name}").mkdir(parents=True)


def delta(inst: Installation, name: str) -> str:
    return next((inst.changes_dir / name / "specs").rglob("spec.md")).read_text()


def ship(inst: Installation, capability: str, requirement: str) -> None:
    spec = inst.specs_dir / "specs" / capability / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(f"## Requirements\n\n### Requirement: {requirement}\n\nIt SHALL.\n")


def test_a_flake_after_an_archived_failing_fix_adds_its_own_requirement(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    archive(installation, TEST, "fix-failing")

    name = str(wait_on_fix(installation, flaked(), unit))

    assert name.endswith("-2")
    assert "## ADDED Requirements" in delta(installation, name)


def test_a_failure_after_an_archived_flake_fix_adds_its_own_requirement(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    archive(installation, FAILING_TEST, "fix-flaky")

    name, _ = ensured(installation, unit)

    assert name.endswith("-2")
    assert "## ADDED Requirements" in delta(installation, name)


def test_a_flake_restates_the_requirement_a_shipped_spec_already_holds(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    archive(installation, TEST, "fix-flaky")
    ship(installation, CAPABILITY, f"`{TEST}` is deterministic")

    name = str(wait_on_fix(installation, flaked(), unit))

    assert "## MODIFIED Requirements" in delta(installation, name)


def test_a_failure_restates_the_requirement_a_shipped_spec_already_holds(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    archive(installation, FAILING_TEST, "fix-failing")
    ship(installation, "failing-tests", f"`{FAILING_TEST}` passes on the base")

    name, _ = ensured(installation, unit)

    assert "## MODIFIED Requirements" in delta(installation, name)
