"""The node records a failure of a tier 2 split with its split, and gives the open-fix gate the
splits the run executes (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from tests.tier2_gate_fakes import Planning
from tests.tier2_wait_fakes import OLD


def test_a_failure_of_an_unheld_split_is_recorded_with_its_split_and_parks(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)

    status = planning.fails(split="acp")

    (entry,) = preexisting_record(planning.installation).entries()
    assert (entry.test, entry.split) == (OLD, "acp")
    assert status == RunStatus.HELD
    assert planning.store.get("add-marker/1").cause is Cause.GATED
    assert len(planning.fix_changes()) == 1


def test_the_gate_is_given_the_splits_the_run_executes(tmp_path: Path) -> None:
    held = Planning(tmp_path / "held", whole=True)
    held.open_fix(OLD, split="acp")
    free = Planning(tmp_path / "free", whole=True)
    free.open_fix(OLD, split="acp")

    held_status = held.tick(tier2_splits=lambda: ("rest", "acp")).status
    free_status = free.tick(tier2_splits=lambda: ("rest", "claude_code")).status

    assert held_status == RunStatus.HELD
    assert not held.ran_tier2
    assert held.needs() != {}
    assert free_status != RunStatus.HELD
    assert free.ran_tier2
    assert free.needs() == {}
    assert free.store.get("add-marker/1").cause is not Cause.GATED
