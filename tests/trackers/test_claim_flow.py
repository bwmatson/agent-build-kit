"""The claim: free group items become the sync account's before the unit starts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
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
