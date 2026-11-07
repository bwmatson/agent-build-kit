"""The hold passes its blocking to the tracker design only when the board blocks (spec:
external-hold-adoption)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.external_file import (
    HELD,
    Hold,
    blocked_groups,
    hold_rows,
    hold_status_lines,
    hold_text,
    read_holds,
)
from agent_build_kit.trackers.reconciler import PassReport
from agent_build_kit.trackers.start_decision import start_decision
from tests.trackers.adoption_support import adopted_board
from tests.trackers.board_support import CHANGE, covering
from tests.trackers.reconciler_support import World
from tests.trackers.start_support import PERSON

HANDED_OVER = "handed_over"
NOBODY = "nobody assigned on the board"
NOW = datetime(2026, 1, 2, tzinfo=UTC)
UNIT = f"{CHANGE}/1"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def sync(world: World) -> PassReport:
    return world.run([covering(UNIT, (1,))])


def assign(world: World, item_id: str) -> None:
    """The person picks the item up on the board."""
    world.tracker.as_identity(PERSON).claim(item_id)


def unassign(world: World, item_id: str) -> None:
    world.tracker.as_identity(PERSON).set_assignee(item_id, "")


def the_hold(world: World) -> Hold:
    (hold,) = read_holds(world.change_dir)
    return hold


def tracker_skips(world: World) -> bool:
    decision = start_decision(covering(UNIT, (1,)), changes_dir=world.changes_dir, claim=False)
    return decision.outcome != "start"


def blocked(world: World) -> bool:
    """Whether the unit cannot start: by the hold or by the claim gate's start check."""
    return 1 in blocked_groups(world.change_dir) or tracker_skips(world)


def test_a_group_item_assigned_to_a_person_hands_the_hold_over_naming_them(
    tmp_path: Path,
) -> None:
    world, _, group = adopted_board(tmp_path, ["change", "group"])
    assign(world, group.id)

    sync(world)

    hold = the_hold(world)
    assert hold.status == HANDED_OVER
    assert PERSON in hold.note
    assert tracker_skips(world)
    (row,) = hold_rows(world.changes_dir, [], NOW)
    assert NOBODY not in hold_text(row)


def test_an_adopted_group_item_with_nobody_assigned_keeps_the_hold_and_says_so(
    tmp_path: Path,
) -> None:
    world, _, _ = adopted_board(tmp_path, ["change", "group"])

    sync(world)

    assert the_hold(world).status == HELD
    assert 1 in blocked_groups(world.change_dir)
    (row,) = hold_rows(world.changes_dir, [], NOW)
    assert NOBODY in hold_text(row)
    assert any(NOBODY in line for line in hold_status_lines(world.changes_dir, [], NOW))


def test_an_assignment_on_a_task_item_is_enough(tmp_path: Path) -> None:
    world, _, _ = adopted_board(tmp_path, ["change", "group", "task"])
    sync(world)
    assert the_hold(world).status == HELD
    assign(world, world.item_id(f"{CHANGE}:1.1"))

    sync(world)

    hold = the_hold(world)
    assert hold.status == HANDED_OVER
    assert PERSON in hold.note
    assert tracker_skips(world)


@pytest.mark.parametrize("assign_before_first_sync", [True, False])
def test_the_unit_is_blocked_at_every_step_in_either_order(
    tmp_path: Path, assign_before_first_sync: bool
) -> None:
    world, _, group = adopted_board(tmp_path, ["change", "group"])
    steps: list[bool] = [blocked(world)]
    if assign_before_first_sync:
        assign(world, group.id)
        steps.append(blocked(world))
        sync(world)
    else:
        sync(world)
        steps.append(blocked(world))
        assign(world, group.id)
        steps.append(blocked(world))
        sync(world)
    steps.append(blocked(world))

    assert all(steps)
    assert the_hold(world).status == HANDED_OVER


def test_clearing_the_assignment_later_does_not_revive_the_hold(tmp_path: Path) -> None:
    world, _, group = adopted_board(tmp_path, ["change", "group"])
    assign(world, group.id)
    sync(world)
    assert the_hold(world).status == HANDED_OVER

    unassign(world, group.id)
    sync(world)

    hold = the_hold(world)
    assert hold.status == HANDED_OVER
    assert PERSON in hold.note
