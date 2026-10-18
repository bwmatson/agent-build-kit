"""A gated unit takes no room under the limit on units in progress, no build slot, and lends no
priority to what it waits on while the round leaves it out (spec: split-start-gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, Priority
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    gate_round(monkeypatch)


def in_review(store: UnitStore, uid: str) -> None:
    fresh(store, uid, "rest")
    store.set_state(uid, IN_REVIEW, branch=f"spec/{uid}", pr=5)


def test_two_gated_units_and_one_in_progress_leave_room_for_a_ready_unit_of_another_split(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 2})
    store = store_of(inst)
    in_review(store, "busy/1")
    fresh(store, "gated/1", "acp", priority=Priority.FIX)
    fresh(store, "gated/2", "acp", priority=Priority.FIX)
    fresh(store, "free/1", "rest")

    assert round_ids(inst, store) == ["free/1"]


def test_a_gated_unit_does_not_make_the_queue_of_its_project_read_as_full(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 1})
    store = store_of(inst)
    fresh(store, "gated/1", "acp", priority=Priority.FIX)
    fresh(store, "free/1", "rest")

    waits = cli.wait_reasons(
        inst, store.all(), started=set(), building=set(), only=frozenset(), usage_paused=False
    )

    assert waits["free/1"].reason is WaitReason.READY
    assert waits["gated/1"].reason is WaitReason.SPLIT
    assert round_ids(inst, store) == ["free/1"]


def test_with_four_slots_the_most_urgent_ready_unit_being_gated_four_others_start(
    tmp_path: Path,
) -> None:
    inst = installation(
        tmp_path,
        acp=True,
        project_limits={"max_concurrent_stacks": 4, "max_units_in_progress": 50},
    )
    store = store_of(inst)
    fresh(store, "gated/1", "acp", priority=Priority.FIX)
    for n in range(1, 5):
        fresh(store, f"free{n}/1", "rest")

    assert sorted(round_ids(inst, store)) == [f"free{n}/1" for n in range(1, 5)]


def test_a_gated_unit_lends_no_priority_to_the_unit_it_waits_on(tmp_path: Path) -> None:
    inst = installation(
        tmp_path,
        acp=True,
        project_limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
    )
    store = store_of(inst)
    fresh(store, "parent/1", "rest", priority=Priority.LOW)
    fresh(store, "gated/1", "acp", priority=Priority.FIX, depends_on=("parent/1",))
    fresh(store, "other/1", "rest", priority=Priority.NORMAL)

    assert round_ids(inst, store) == ["other/1"]
