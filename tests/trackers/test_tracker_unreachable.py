"""A tracker that cannot be read holds the start by default; `on_error: start` starts the unit
and the admission record says the tracker was not checked."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    read_admissions,
)
from agent_build_kit.trackers.start_decision import start_decision
from tests.forges.stand_in import StandInForge, lookup
from tests.split_start_support import fresh, gate_round, round_ids, store_of
from tests.trackers.board_support import TYPES
from tests.trackers.reconciler_support import Call
from tests.trackers.start_support import FIRST, board, board_in
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def refuse_every_call(call: Call) -> Exception | None:
    return HostUnavailable(call.name, "the board refused the call", 3)


def on_error_start() -> None:
    """The repo's tracker section with `on_error: start`, the board unchanged."""
    configure(
        app={
            "kind": "azure_devops",
            "levels": ["change", "group"],
            "on_error": "start",
            "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        }
    )


def claim_records(inst, unit_id: str) -> list[AdmissionRecord]:  # noqa: ANN001
    return [
        record
        for record in read_admissions(inst.state_dir / ADMISSIONS_NAME)
        if record.kind == "claim" and record.unit == unit_id
    ]


def test_a_refused_tracker_is_a_wait_that_says_the_tracker_is_unreachable(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    world.tracker.fail = refuse_every_call

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "wait"
    assert "tracker unreachable" in decision.reason


def test_the_wait_is_recorded_and_a_later_tick_admits_the_unit(tmp_path: Path) -> None:
    world, inst = board_in(tmp_path)
    store = store_of(inst)
    fresh(store, FIRST)
    world.tracker.fail = refuse_every_call

    assert round_ids(inst, store) == []

    held = claim_records(inst, FIRST)
    assert held, "the wait is written as a claim record"
    assert held[-1].outcome == "wait"
    assert "tracker unreachable" in held[-1].reason

    world.tracker.fail = lambda call: None

    assert round_ids(inst, store) == [FIRST]


def test_the_start_setting_starts_a_unit_the_tracker_could_not_be_asked_about(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    on_error_start()
    world.tracker.fail = refuse_every_call

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "start"
    assert "not checked" in decision.reason


def test_the_admission_record_says_the_tracker_was_not_checked(tmp_path: Path) -> None:
    world, inst = board_in(tmp_path)
    store = store_of(inst)
    fresh(store, FIRST)
    on_error_start()
    world.tracker.fail = refuse_every_call

    assert round_ids(inst, store) == [FIRST]

    made = claim_records(inst, FIRST)
    assert made, "the start is written as a claim record"
    assert made[-1].outcome == "start"
    assert "not checked" in made[-1].reason


def test_a_remote_that_cannot_be_asked_still_waits_when_the_setting_is_start(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    on_error_start()

    decision = start_decision(
        unit,
        changes_dir=world.changes_dir,
        for_repo=lookup(StandInForge()),
        remote_head_of=lambda repo, branch: None,
    )

    assert decision.outcome == "wait"
    assert "tracker" not in decision.reason
    assert decision.claimed == ()
