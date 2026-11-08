"""A recording of the base's selection data waits behind every unit's check for a slot (spec:
selection-data-comes-from-the-base)."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from agent_build_kit.pipeline.unit_test_slots import RECORDING_RANK, unit_test_slot
from tests.unit_test_slot_fakes import waiting_run
from tests.waiting import wait_for


def test_the_recording_rank_is_after_every_rank_a_unit_can_wait_at() -> None:
    assert RECORDING_RANK > (2, 10**6)


def test_a_unit_check_is_served_before_a_recording_that_began_waiting_first(
    tmp_path: Path,
) -> None:
    order: list[str] = []
    with ExitStack() as stack:
        with unit_test_slot(tmp_path, 1, holder="holder/1"):
            recording = stack.enter_context(
                waiting_run(tmp_path, "base-recording", rank=RECORDING_RANK, order=order)
            )
            recording.until_waiting(tmp_path, "base-recording")
            check = stack.enter_context(waiting_run(tmp_path, "unit/1", rank=(2, 4), order=order))
            check.until_waiting(tmp_path, "unit/1")
        wait_for(lambda: len(order) == 1, what="the first waiter to take the slot")
        assert order == ["unit/1"]
        check.release.set()
        wait_for(lambda: len(order) == 2, what="the recording to take the slot")

    assert order == ["unit/1", "base-recording"]
