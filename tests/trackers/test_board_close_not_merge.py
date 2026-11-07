"""A group item closed on the board is not a merge of its unit (spec: external-hold-adoption)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_done import record_hand_merge
from agent_build_kit.pipeline.external_file import add_hold
from agent_build_kit.pipeline.tracker_file import ConflictRecord, read_tracker
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.trackers.apply import Applied, apply_changes
from agent_build_kit.trackers.poll import poll_board
from tests.external_support import hold
from tests.forges.stand_in import StandInForge
from tests.split_start_support import fresh, store_of
from tests.trackers.board_support import CHANGE
from tests.trackers.reconciler_support import World
from tests.trackers.start_support import FIRST, PERSON, board_in, item

pytestmark = pytest.mark.usefixtures("scripted_engine")

PULL = 31
COMMIT = "d" * 40
CLOSED_NOTE = "merge not recorded"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def inbound(world: World, store: UnitStore) -> Applied:
    changes = poll_board("app", state_dir=world.state_dir, log=world.logs.append)
    return apply_changes(
        "app",
        changes,
        changes_dir=world.changes_dir,
        store=store,
        log=world.logs.append,
    )


def open_conflicts(world: World) -> list[ConflictRecord]:
    recorded = read_tracker(world.change_dir)
    assert recorded is not None
    return [record for record in recorded.conflicts if record.status == "open"]


def held_unit_with_closed_group_item(
    tmp_path: Path,
) -> tuple[World, Installation, UnitStore, str, Applied]:
    world, inst = board_in(tmp_path)
    store = store_of(inst)
    fresh(store, FIRST)
    add_hold(inst.changes_dir / CHANGE, hold((1,)))
    inbound(world, store)  # the cursor is at the end of the push
    group = item(world, "1")
    world.tracker.as_identity(PERSON).update(group, {"state": "done"})
    return world, inst, store, group, inbound(world, store)


def test_a_group_item_closed_on_the_board_records_a_conflict_and_does_not_merge(
    tmp_path: Path,
) -> None:
    world, _, store, group, applied = held_unit_with_closed_group_item(tmp_path)

    assert any(CLOSED_NOTE in conflict.note for conflict in applied.conflicts)
    assert [record.item_id for record in open_conflicts(world)] == [group]
    assert store.get(FIRST).state != MERGED


def test_recording_the_verified_hand_merge_merges_the_unit_and_closes_the_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst, store, _, _ = held_unit_with_closed_group_item(tmp_path)
    assert open_conflicts(world)
    forge = StandInForge()
    forge.merged[PULL] = COMMIT
    monkeypatch.setattr(inst, "forge_of", lambda repo: (forge, forge.repo_id()))

    record_hand_merge(inst, store, CHANGE, (1,), pr=PULL)
    inbound(world, store)

    assert store.get(FIRST).state == MERGED
    assert open_conflicts(world) == []
