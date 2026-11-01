"""No code writes a fix change for a failing test but the regression agent (spec:
regression-agent): the modules that used to hold the templates no longer expose a change writer,
and the gate before a full e2e-test run only waits on a change that is open."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import flakes, untouched_failures
from agent_build_kit.pipeline.wiring import build_on_e2e_gate
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD
from tests.regression_agent_fakes import DefaultAgent

GONE = {
    flakes: ("wait_on_fix", "requirement_shipped", "CAPABILITY"),
    untouched_failures: ("ensure_fix", "wait_on_preexisting", "CAPABILITY"),
}


@pytest.mark.parametrize(
    ("module", "name"), [(module, name) for module, names in GONE.items() for name in names]
)
def test_the_template_writers_are_gone(module: object, name: str) -> None:
    assert not hasattr(module, name)


def changes_of(planning: Planning) -> set[str]:
    return {p.name for p in planning.installation.changes_dir.iterdir()}


def gate(planning: Planning) -> list[str]:
    return build_on_e2e_gate(planning.store, planning.installation, log=lambda message: None)(
        planning.store.get("add-marker/1"), splits=None
    )


def test_the_gate_waits_on_an_open_change_and_writes_nothing(
    tmp_path: Path, no_real_regression_agent: DefaultAgent
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD)
    before, runs = changes_of(planning), len(no_real_regression_agent.runtime.requests)

    assert gate(planning) == [fix]

    assert changes_of(planning) == before
    assert len(no_real_regression_agent.runtime.requests) == runs


def test_the_gate_writes_no_change_when_the_fix_was_archived_after_the_failure_was_recorded(
    tmp_path: Path, no_real_regression_agent: DefaultAgent
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix(OLD)
    archive = planning.installation.changes_dir / "archive"
    archive.mkdir()
    (planning.installation.changes_dir / fix).rename(archive / f"2026-03-02-{fix}")
    before, runs = changes_of(planning), len(no_real_regression_agent.runtime.requests)

    assert gate(planning) == []

    assert changes_of(planning) == before
    assert len(no_real_regression_agent.runtime.requests) == runs
