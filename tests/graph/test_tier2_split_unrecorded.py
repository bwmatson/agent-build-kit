"""A failure whose split is unknown is the unit's own, the waiting note names only the tests
that got a fix change, and a held split's failures record nothing (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.tier2_gate_fakes import Planning
from tests.tier2_wait_fakes import OLD, OTHER_OLD, Failing, failure, snapshot_of, verdict_of

UNKNOWN = "unknown"


def test_a_failure_whose_split_is_unknown_is_the_units_own_with_its_output_as_feedback(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path, whole=False)

    status = planning.fails(split=UNKNOWN)

    assert status != RunStatus.HELD
    assert preexisting_record(planning.installation).entries() == []
    assert planning.fix_changes() == []
    stored = planning.store.get("add-marker/1")
    assert stored.cause is not Cause.GATED
    assert stored.feedback.startswith("tier 2 failed:")
    assert OLD in stored.feedback


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


def test_a_held_split_with_failing_tests_records_nothing_and_writes_no_fix_change(
    tmp_path: Path,
) -> None:
    planning = Planning(
        tmp_path,
        whole=False,
        tests=dict(tier2_splits={"acp": {"marker": "runtime_acp", "hold": True}}),
    )

    planning.fails(split="acp")

    assert preexisting_record(planning.installation).entries() == []
    assert planning.fix_changes() == []
