"""A unit records its e2e state: what its e2e-test step came to for the head it pushed
(spec: e2e-before-merge)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import E2eState, UnitStore
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

UNIT_ID = "add-marker/1"


def stored_state(tmp_path: Path) -> E2eState | None:
    return UnitStore(tmp_path / "units.json").get(UNIT_ID).e2e_state


def test_a_passing_e2e_node_records_passed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, tier="e2e-test")

    assert "e2e-test" in recorder.events
    assert stored_state(tmp_path) is E2eState.PASSED


def test_a_failing_e2e_node_records_failed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, e2e_ok=False)

    tick(tmp_path, recorder, tier="e2e-test")

    assert "e2e-test" in recorder.events
    assert stored_state(tmp_path) is E2eState.FAILED


def test_a_unit_test_unit_reaching_review_records_not_required(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, tier="unit-test")

    assert "e2e-test" not in recorder.events
    assert stored_state(tmp_path) is E2eState.NOT_REQUIRED


def test_a_rework_that_pushes_a_new_head_resets_the_state_before_the_next_result(
    tmp_path: Path,
) -> None:
    total = active().global_limits.max_review_rounds
    recorder = fresh(tmp_path)
    recorder.store.record_e2e_state(UNIT_ID, E2eState.PASSED)
    recorder.verdicts = [rejecting("not yet")] * total

    tick(tmp_path, recorder, tier="e2e-test")

    assert "e2e-test" not in recorder.events, "review ended the run before a new result"
    assert stored_state(tmp_path) is None


def test_a_unit_stored_before_this_change_reads_with_no_state(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    path = recorder.store.path
    raw = json.loads(path.read_text())
    raw["units"][0].pop("e2e_state", None)
    path.write_text(json.dumps(raw))

    assert UnitStore(path).get(UNIT_ID).e2e_state is None
