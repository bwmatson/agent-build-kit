"""A failed unit that waited on another unit is requeued once when its wait ends.

A pass records what a failed unit waits on, and the pass that finds the wait over requeues
the unit through `abk requeue`'s own delivery. The record is cleared by the requeue, so a
wait is acted on once; a held unit, a plain failure and a unit parked by another mechanism
are left to their own paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, PLANNED, UnitState
from tests.factories import new_unit
from tests.wait_end_support import CHILD, PARENT, pipeline, save_failure

NOTE = "requeue: its wait ended (waiting on base group 1 is now merged)"


def test_a_store_written_before_the_fields_loads_with_no_wait_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    path = pipe.store.path
    stored = json.loads(path.read_text())

    def without_fields(node):
        if isinstance(node, dict):
            return {
                key: without_fields(value)
                for key, value in node.items()
                if key not in ("waited_on", "wait_ended")
            }
        if isinstance(node, list):
            return [without_fields(item) for item in node]
        return node

    path.write_text(json.dumps(without_fields(stored)))

    unit = UnitStore(path).get(CHILD)

    assert unit.state == FAILED
    assert unit.waited_on == ()
    assert unit.wait_ended == ""
    pipe.pass_()
    assert UnitStore(path).get(CHILD).waited_on == (PARENT,)


def test_a_pass_records_what_a_failed_unit_waits_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()

    pipe.pass_()

    assert pipe.store.get(CHILD).waited_on == (PARENT,)
    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).state == FAILED


def test_the_wait_ending_requeues_the_unit_once_and_keeps_what_it_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, feedback="the check failed", source=FeedbackSource.E2E, guidance="mind x")
    pipe.pass_()
    pipe.merge()

    pipe.passes(3)

    [delivery] = pipe.host.deliveries
    assert delivery["unit"] == CHILD
    assert delivery["kind"] == "requeue"
    kept = pipe.store.get(CHILD)
    assert kept.waited_on == ()
    assert (kept.branch, kept.feedback, kept.guidance) == (
        f"spec/{CHILD}",
        "the check failed",
        "mind x",
    )


def test_the_history_says_the_wait_ended_and_names_the_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    save_failure(pipe, feedback="the check failed", source=FeedbackSource.E2E)
    pipe.pass_()
    pipe.merge()

    pipe.pass_()

    after = pipe.store.get(CHILD)
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)
    assert pipe.wait_ended_notes() == [NOTE]
    assert (after.branch, after.feedback) == (f"spec/{CHILD}", "the check failed")


def test_a_unit_with_a_thread_is_delivered_the_wait_ended_text_as_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()

    pipe.pass_()

    [delivery] = pipe.host.deliveries
    assert f"requeue: {delivery['reason']}" == NOTE
    assert pipe.wait_ended_notes() == [NOTE]


def test_each_prerequisite_is_named_in_the_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed(PARENT, "other/1")
    pipe.pass_()
    pipe.merge(PARENT, "other/1")

    pipe.pass_()

    [note] = pipe.wait_ended_notes()
    assert "base group 1" in note and "other group 1" in note


def test_a_unit_that_fails_again_and_waits_on_nothing_is_not_requeued_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    pipe.pass_()
    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)

    pipe.passes(4)

    assert pipe.store.get(CHILD).state == FAILED
    assert len(pipe.wait_ended_notes()) == 1
    assert pipe.store.get(CHILD).waited_on == ()


def test_a_second_prerequisite_added_later_is_a_new_wait_and_a_second_requeue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    pipe.pass_()
    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)
    pipe.store.upsert([new_unit(PARENT), new_unit(CHILD, depends_on=(PARENT,)), new_unit("more/1")])
    pipe.merge()
    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)
    pipe.store.set_state("more/1", UnitState.RUNNING)
    pipe.store.set_dependencies(CHILD, (PARENT, "more/1"))

    pipe.pass_()

    assert pipe.store.get(CHILD).waited_on == ("more/1",)

    pipe.merge("more/1")
    pipe.passes(2)

    assert len(pipe.wait_ended_notes()) == 2


def test_a_prerequisite_joining_while_the_first_holds_keeps_one_record_and_one_requeue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.store.upsert(
        [new_unit(PARENT), new_unit("more/1"), new_unit(CHILD, depends_on=(PARENT, "more/1"))]
    )
    pipe.store.set_state(PARENT, UnitState.RUNNING)
    pipe.store.set_state("more/1", UnitState.RUNNING)
    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)

    pipe.pass_()

    assert pipe.store.get(CHILD).waited_on == (PARENT, "more/1")

    pipe.merge(PARENT)
    pipe.pass_()
    assert pipe.host.deliveries == [], "one prerequisite still holds"

    pipe.merge("more/1")
    pipe.passes(2)

    assert [delivery["unit"] for delivery in pipe.host.deliveries] == [CHILD]


def test_a_held_unit_is_not_requeued_when_its_prerequisite_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.store.set_state(CHILD, HELD)

    pipe.pass_()
    assert pipe.store.get(CHILD).waited_on == ()
    pipe.merge()
    pipe.passes(2)

    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).state == HELD


def test_a_unit_waiting_then_held_carries_no_record_and_is_judged_afresh_when_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.store.set_state(CHILD, HELD)
    pipe.pass_()
    assert pipe.store.get(CHILD).waited_on == ()
    pipe.merge()

    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)
    pipe.passes(2)

    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).state == FAILED


def test_a_failed_unit_that_has_not_waited_is_untouched_by_any_number_of_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.store.upsert([new_unit("plain/1")])
    pipe.store.set_state("plain/1", UnitState.FAILED, branch="spec/plain/1", cause=Cause.FAILED)
    before = pipe.store.get("plain/1")

    pipe.passes(5)

    assert pipe.store.get("plain/1") == before
    assert pipe.host.deliveries == []


def test_a_unit_parked_by_the_failure_fix_mechanism_is_left_to_its_own_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.store.set_state(CHILD, PLANNED, cause=Cause.GATED)
    pipe.store.set_gated_requeue(CHILD, RequeueReason.RESUME)

    pipe.pass_()
    pipe.merge()
    pipe.passes(2)

    parked = pipe.store.get(CHILD)
    assert (parked.state, parked.cause, parked.waited_on) == (PLANNED, Cause.GATED, ())
    assert parked.gated_requeue is RequeueReason.RESUME
    assert pipe.host.deliveries == []


def test_a_unit_a_person_requeued_while_it_waited_resumes_by_the_gated_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    assert cli.requeue(pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None) == 0
    assert (pipe.store.get(CHILD).state, pipe.store.get(CHILD).cause) == (PLANNED, Cause.GATED)
    pipe.merge()

    pipe.pass_()

    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).waited_on == ()
    cli.release_gated(pipe.inst, pipe.store)
    [delivery] = pipe.host.deliveries
    assert delivery["requeue"] is RequeueReason.RESUME


def test_a_planned_unit_never_started_is_not_delivered_to_by_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.store.upsert([new_unit(PARENT), new_unit("late/1", depends_on=(PARENT,))])
    pipe.merge()

    pipe.passes(2)

    assert pipe.store.get("late/1").state == PLANNED
    assert pipe.host.deliveries == []


def test_a_unit_in_flight_is_skipped_and_requeued_once_it_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()

    pipe.pass_(in_flight=(CHILD,))
    assert pipe.host.deliveries == []

    pipe.pass_()
    assert [delivery["unit"] for delivery in pipe.host.deliveries] == [CHILD]


def test_a_branch_held_by_another_run_leaves_the_unit_failed_with_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    pipe.host.busy = True

    pipe.pass_()

    assert pipe.store.get(CHILD).state == FAILED
    assert pipe.store.get(CHILD).waited_on == (PARENT,)
    assert pipe.host.deliveries == []

    pipe.host.busy = False
    pipe.pass_()

    assert [delivery["unit"] for delivery in pipe.host.deliveries] == [CHILD]
    assert pipe.store.get(CHILD).waited_on == ()


def test_the_requeue_is_not_held_by_the_limit_on_units_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, project_limits=dict(max_units_in_progress=1))
    pipe.store.upsert([new_unit(PARENT), new_unit(CHILD, depends_on=(PARENT,)), new_unit("busy/1")])
    pipe.store.set_state(PARENT, UnitState.RUNNING)
    pipe.store.set_state(CHILD, UnitState.FAILED, branch=f"spec/{CHILD}", cause=Cause.FAILED)
    pipe.store.set_state("busy/1", UnitState.RUNNING)
    pipe.pass_()
    pipe.merge()

    pipe.pass_()

    assert [delivery["unit"] for delivery in pipe.host.deliveries] == [CHILD]


def test_a_usage_pause_still_takes_the_delivery_and_starts_no_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.pipeline.usage_guard import Decision

    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda reading: Decision(may_start=False, reason="session at 99%")
    )
    started: set[str] = set()

    cli.run_round(
        pipe.inst, pipe.store, building=set(), started=started, only=frozenset(), submit=False
    )

    assert [delivery["unit"] for delivery in pipe.host.deliveries] == [CHILD]
    assert started == set()
