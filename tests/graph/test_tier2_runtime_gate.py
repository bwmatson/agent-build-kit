"""The node records a failure of a runtime group with its runtime, treats a failure whose
runtime is unknown as the unit's own, and a blocked runtime records nothing (spec:
tier2-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.untouched_failures import PREFIX, preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.tier2_gate_fakes import Planning
from tests.tier2_wait_fakes import OLD, OTHER_OLD, Failing, failure, snapshot_of, verdict_of

UNKNOWN = "unknown"


def fails(planning: Planning, *, group: str) -> RunStatus:
    """The unit's tier 2 run fails on `OLD` of runtime group `group`, which the base fails too."""
    tier2 = Failing(planning.recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,), group=group))
    outcome = planning.tick(
        run_tier2=tier2.run,
        tier2_verdict=tier2.judged,
        on_preexisting=build_on_preexisting(
            planning.store, planning.installation, log=lambda m: None
        ),
    )
    return outcome.status


def fix_changes(planning: Planning) -> list[str]:
    return sorted(c for c in planning.changes() if c.startswith(PREFIX))


def test_an_acp_failure_of_an_unblocked_run_is_recorded_with_its_runtime_and_parks(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)

    status = fails(planning, group="acp")

    (entry,) = preexisting_record(planning.installation).entries()
    assert (entry.test, entry.runtime) == (OLD, "acp")
    assert status == RunStatus.HELD
    assert planning.store.get("add-marker/1").cause is Cause.GATED
    assert len(fix_changes(planning)) == 1


def test_a_failure_whose_runtime_is_unknown_is_the_units_own_with_its_output_as_feedback(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)

    status = fails(planning, group=UNKNOWN)

    assert status != RunStatus.HELD
    assert preexisting_record(planning.installation).entries() == []
    assert fix_changes(planning) == []
    stored = planning.store.get("add-marker/1")
    assert stored.cause is not Cause.GATED
    assert stored.feedback.startswith("tier 2 failed:")
    assert OLD in stored.feedback


def test_the_gate_is_given_the_groups_the_run_executes(tmp_path: Path) -> None:
    held = Planning(tmp_path / "held", whole=True)
    held.open_fix(OLD, group="acp")
    free = Planning(tmp_path / "free", whole=True)
    free.open_fix(OLD, group="acp")

    held_status = held.tick(tier2_runtimes=lambda: ("base", "acp")).status
    free_status = free.tick(tier2_runtimes=lambda: ("base", "claude_code")).status

    assert held_status == RunStatus.HELD
    assert not held.ran_tier2
    assert held.needs() != {}
    assert free_status != RunStatus.HELD
    assert free.ran_tier2
    assert free.needs() == {}
    assert free.store.get("add-marker/1").cause is not Cause.GATED


def test_the_waiting_note_names_only_the_tests_that_got_a_fix_change(tmp_path: Path) -> None:
    planning = Planning(tmp_path, whole=False)
    verdict = verdict_of(old=(OLD,), group="acp")
    verdict = verdict.model_copy(
        update={"pre_existing": [*verdict.pre_existing, failure(OTHER_OLD, UNKNOWN)]}
    )
    tier2 = Failing(planning.recorder.events, snapshot_of(OLD, OTHER_OLD), verdict)

    planning.tick(
        run_tier2=tier2.run,
        tier2_verdict=tier2.judged,
        on_preexisting=build_on_preexisting(
            planning.store, planning.installation, log=lambda m: None
        ),
    )

    note = planning.store.get("add-marker/1").note
    assert OLD in note
    assert OTHER_OLD not in note


def test_a_blocked_runtime_with_failing_tests_records_nothing_and_writes_no_fix_change(
    tmp_path: Path,
) -> None:
    planning = Planning(
        tmp_path,
        whole=False,
        tests=dict(tier2_splits={"acp": {"marker": "runtime_acp", "hold": True}}),
    )

    fails(planning, group="acp")

    assert preexisting_record(planning.installation).entries() == []
    assert fix_changes(planning) == []
