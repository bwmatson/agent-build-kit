"""The verdict recorded by the review node reads the e2e step as the run will treat it: an
e2e-test unit whose tier is deferred is `deferred` at its approving round, before the pull request
records it (spec: review-verdict-e2e-state)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.unit_store import E2eState
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

UNIT_ID = unit().id
DEFERRAL = "the e2e-test result was deferred to verify"
NOT_RUN = "the e2e-test gate has no result"
APPROVED_AUTO = json.dumps({"approved": True, "feedback": "", "classification": "auto"})


def final_entry(
    tmp_path: Path, *, before_merge: str, auto_land: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The approving round's entry for an e2e-test unit, with review on."""
    make_installation(
        tmp_path,
        global_limits={"e2e_before_merge": before_merge},
        review={"enabled": True, "auto_land": auto_land or {}},
    )
    recorder = fresh(tmp_path, tier="e2e-test")
    recorder.verdicts = [APPROVED_AUTO]
    build(tmp_path, recorder, run_e2e=lambda **_: (True, ""))
    entry = json.loads((tmp_path / VERDICTS).read_text())[UNIT_ID]
    assert entry["final"] is True
    return entry


def test_a_deferred_unit_is_recorded_light_naming_the_deferral(tmp_path: Path) -> None:
    entry = final_entry(tmp_path, before_merge="deferred")

    assert (entry["tier"], entry["evidence_tier"]) == ("light", "light")
    assert entry["reason"] == DEFERRAL


def test_the_allowance_leaves_a_deferred_unit_with_no_floor_from_the_e2e_result(
    tmp_path: Path,
) -> None:
    entry = final_entry(tmp_path, before_merge="deferred", auto_land={"allow_deferred_e2e": True})

    assert entry["reason"] != DEFERRAL
    assert entry["evidence_tier"] == "auto"


def test_a_required_unit_is_still_full_with_the_gate_not_yet_run(tmp_path: Path) -> None:
    entry = final_entry(tmp_path, before_merge="required")

    assert entry["tier"] == "full"
    assert entry["reason"] == NOT_RUN


def test_a_rework_clears_the_e2e_state_so_the_new_head_is_a_missing_gate(tmp_path: Path) -> None:
    make_installation(
        tmp_path,
        global_limits={"e2e_before_merge": "required"},
        review={"enabled": True},
    )
    recorder = fresh(tmp_path, tier="e2e-test")
    recorder.store.record_e2e_state(UNIT_ID, E2eState.PASSED)
    recorder.verdicts = [
        json.dumps({"approved": False, "feedback": "tidy the error message"}),
        APPROVED_AUTO,
    ]
    written: list[E2eState | None] = []
    record = recorder.store.record_e2e_state

    def recording(unit_id: str, state: E2eState | None) -> None:
        written.append(state)
        record(unit_id, state)

    recorder.store.record_e2e_state = recording  # type: ignore[method-assign]
    build(tmp_path, recorder, run_e2e=lambda **_: (True, ""))

    assert written[0] is None, "cleared by the rework, before the new head is reviewed"
    entry = json.loads((tmp_path / VERDICTS).read_text())[UNIT_ID]
    assert entry["final"] is True
    assert (entry["tier"], entry["reason"]) == ("full", NOT_RUN)
