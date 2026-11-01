"""The start decision: a unit starts only when the sync account owns what it covers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import ready_units
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.start_decision import start_decision, start_view
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import RecordingTracker, World
from tests.trackers.start_support import PERSON, board, item, taken_by_person


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def decide(world: World, unit):  # noqa: ANN001, ANN201
    return start_decision(unit, changes_dir=world.changes_dir)


def test_a_group_item_assigned_to_a_person_is_skipped_naming_them(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    taken = taken_by_person(world, "1")

    decision = decide(world, unit)

    assert decision.outcome == "skip"
    assert "assigned to" in decision.reason
    assert PERSON in decision.reason
    assert decision.items == (taken,)


def test_one_of_two_covered_group_items_taken_skips_the_unit_and_claims_nothing(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    taken = taken_by_person(world, "2")
    world.tracker.calls.clear()

    decision = decide(world, unit)

    assert decision.outcome == "skip"
    assert PERSON in decision.reason
    assert decision.items == (taken,)
    assert world.tracker.writes() == []


def test_a_task_item_taken_by_a_person_skips_an_otherwise_free_group_item(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group", "task"])
    taken = taken_by_person(world, "1.1")

    decision = decide(world, unit)

    assert decision.outcome == "skip"
    assert PERSON in decision.reason
    assert decision.items == (taken,)


def test_group_items_already_the_sync_accounts_start_with_no_further_assignment(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    for key in ("1", "2"):
        world.tracker.claim(item(world, key))
    world.tracker.calls.clear()

    decision = decide(world, unit)

    assert decision.outcome == "start"
    assert world.tracker.writes() == []


def test_without_a_group_level_the_lowest_level_in_use_is_checked(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "task"])
    taken = taken_by_person(world, "1.2")

    decision = decide(world, unit)

    assert decision.outcome == "skip"
    assert PERSON in decision.reason
    assert decision.items == (taken,)


def test_a_skipped_unit_takes_no_slot_and_another_ready_unit_is_admitted(
    tmp_path: Path,
) -> None:
    world, skipped = board(tmp_path, ["change", "group"])
    taken_by_person(world, "1")
    other = covering(f"{CHANGE}/2", (2,))

    view = start_view([skipped, other], lambda each: decide(world, each))
    ready = ready_units(view, max_concurrent=5, depth_cap=10, max_units_in_progress=1)

    assert [each.id for each in ready] == [other.id]


def test_a_group_item_the_sync_has_not_mirrored_yet_makes_the_unit_wait(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, board_section(["change", "group"]), RecordingTracker())
    unit = covering(f"{CHANGE}/1", (1,))

    decision = decide(world, unit)

    assert decision.outcome == "wait"
    assert "no board item yet" in decision.reason
    assert world.tracker.made("create") == []
    assert world.tracker.writes() == []


def test_an_item_assigned_to_the_identity_of_the_credential_is_the_kits(tmp_path: Path) -> None:
    operator = LocalTracker(who="operator-pat")
    world, unit = board(tmp_path, ["change", "group"], tracker=operator)
    held = operator.claim(item(world, "1"))

    assert held
    assert decide(world, unit).outcome == "start"


def test_an_item_assigned_to_any_other_identity_holds_the_unit(tmp_path: Path) -> None:
    operator = LocalTracker(who="operator-pat")
    world, unit = board(tmp_path, ["change", "group"], tracker=operator)
    taken = taken_by_person(world, "1")

    decision = decide(world, unit)

    assert decision.outcome == "skip"
    assert PERSON in decision.reason
    assert decision.items == (taken,)
