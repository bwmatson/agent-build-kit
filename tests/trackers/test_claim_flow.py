"""The claim: free group items become the sync account's before the unit starts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.trackers.base import Capabilities
from agent_build_kit.trackers.start_decision import start_decision
from tests.split_start_support import fresh, gate_round, round_ids, store_of
from tests.trackers.reconciler_support import SYNC, Call, RecordingTracker
from tests.trackers.start_support import FIRST, PERSON, board, board_in, item

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def taken_when_claimed(world, key: str) -> None:  # noqa: ANN001
    """Make a person take the item of `key` in the instant before the kit's claim of it lands."""
    target = item(world, key)

    def fail(call: Call) -> Exception | None:
        if call.name == "claim" and call.args == (target,):
            world.tracker.as_identity(PERSON).claim(target)
        return None

    world.tracker.fail = fail


def test_unassigned_group_items_are_claimed_before_the_decision_is_start(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    ids = (item(world, "1"), item(world, "2"))

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "start"
    assert decision.claimed == ids
    assert [world.tracker.get(item_id).assignees for item_id in ids] == [(SYNC,), (SYNC,)]


def test_each_claim_is_recorded_in_the_units_history(tmp_path: Path) -> None:
    world, inst = board_in(tmp_path)
    store = store_of(inst)
    fresh(store, FIRST)

    assert round_ids(inst, store) == [FIRST]

    claims = [entry for entry in store.history(FIRST) if entry.get("event") == "claim"]
    assert [entry.get("item") for entry in claims] == [item(world, "1")]


def test_a_group_item_taken_between_the_read_and_the_claim_is_not_held(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    taken_when_claimed(world, "1")

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert "claim lost" in decision.reason
    assert PERSON in decision.reason
    assert decision.claimed == ()
    assert world.tracker.get(item(world, "1")).assignees == (PERSON,)


def test_a_lost_second_claim_releases_the_first(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    taken_when_claimed(world, "2")

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert "claim lost" in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == ()
    assert world.tracker.get(item(world, "2")).assignees == (PERSON,)


def test_only_the_group_items_are_claimed_when_the_board_has_tasks(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group", "task"])
    group = item(world, "1")
    tasks = [item(world, "1.1"), item(world, "1.2")]

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "start"
    assert decision.claimed == (group,)
    assert world.tracker.get(group).assignees == (SYNC,)
    assert [world.tracker.get(task).assignees for task in tasks] == [(), ()]


def test_a_failure_while_claiming_releases_the_claims_made_and_waits(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    target = item(world, "2")

    def fail(call: Call) -> Exception | None:
        if call.name == "claim" and call.args == (target,):
            return HostUnavailable("claim", "the board is down", 3)
        return None

    world.tracker.fail = fail

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "wait"
    assert "the board is down" in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_release_that_fails_is_recorded_and_does_not_hide_the_lost_claim(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    taken_when_claimed(world, "2")
    lose = world.tracker.fail

    def fail(call: Call) -> Exception | None:
        if call.name == "set_assignee":
            return HostUnavailable("set_assignee", "the board is down", 3)
        return lose(call)

    world.tracker.fail = fail

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert "claim lost" in decision.reason
    assert [(a.item, a.outcome) for a in decision.attempts] == [
        (item(world, "1"), "held"),
        (item(world, "2"), "lost"),
        (item(world, "1"), "release failed"),
    ]


def test_the_release_leaves_an_item_a_person_took_after_the_claim(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"], (1, 2))
    first, second = item(world, "1"), item(world, "2")

    def fail(call: Call) -> Exception | None:
        if call.name == "claim" and call.args == (second,):
            world.tracker.as_identity(PERSON).set_assignee(first, PERSON)
            world.tracker.as_identity(PERSON).claim(second)
        return None

    world.tracker.fail = fail

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert world.tracker.get(first).assignees == (PERSON,)


def test_a_lost_claim_and_the_release_it_causes_are_recorded_in_the_history(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    store = store_of(inst)
    fresh(store, FIRST, groups=(1, 2))
    taken_when_claimed(world, "2")

    assert round_ids(inst, store) == []

    claims = [
        (entry.get("item"), entry.get("outcome"))
        for entry in store.history(FIRST)
        if entry.get("event") == "claim"
    ]
    assert claims == [
        (item(world, "1"), "held"),
        (item(world, "2"), "lost"),
        (item(world, "1"), "released"),
    ]


def test_without_a_revision_check_the_earlier_assignee_wins_and_the_unit_does_not_start(
    tmp_path: Path,
) -> None:
    plain = RecordingTracker(capabilities=Capabilities(revision_check=False))
    world, unit = board(tmp_path, ["change", "group"], tracker=plain)
    taken_when_claimed(world, "1")

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert PERSON in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == (PERSON,)
