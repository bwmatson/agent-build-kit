"""The round holds a unit whose board item a person owns, and only that unit."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of, worked
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import Call, RecordingTracker, World
from tests.trackers.start_support import taken_by_person

pytestmark = pytest.mark.usefixtures("scripted_engine")

FIRST = f"{CHANGE}/1"
SECOND = f"{CHANGE}/2"


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def board_in(tmp_path: Path) -> tuple[World, Installation]:
    """The installation of a repo with a tracker, and its board pushed into the changes folder
    the round reads."""
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 5})
    folder = inst.changes_dir.parent
    folder.mkdir(parents=True, exist_ok=True)
    world = World(folder, board_section(["change", "group"]), RecordingTracker())
    world.run([covering(FIRST, (1,)), covering(SECOND, (2,))])
    return world, inst


def test_a_planned_unit_whose_item_a_person_owns_is_not_ready_while_another_is(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    taken_by_person(world, "1")
    store = store_of(inst)
    fresh(store, FIRST)
    fresh(store, SECOND)

    waits = cli.wait_reasons(
        inst, store.all(), started=set(), building=set(), only=frozenset(), usage_paused=False
    )

    assert waits[SECOND].reason is WaitReason.READY
    assert waits[FIRST].reason is not WaitReason.READY
    assert round_ids(inst, store) == [SECOND]


def test_a_unit_with_a_branch_of_its_own_is_not_asked_and_keeps_its_treatment(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    taken_by_person(world, "1")
    store = store_of(inst)
    worked(store, FIRST, "rest")
    world.tracker.calls.clear()

    ready = round_ids(inst, store)

    assert ready == [FIRST]
    assert world.tracker.made("get") == []
    assert world.tracker.made("identity") == []


def test_a_board_failure_holds_that_repos_unit_and_another_repos_unit_still_starts(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)

    def fail(call: Call) -> Exception | None:
        return HostUnavailable("get", "the board is down", 3) if call.name == "get" else None

    world.tracker.fail = fail
    store = store_of(inst)
    fresh(store, FIRST)
    fresh(store, "elsewhere/1", repo="platform")

    assert round_ids(inst, store) == ["elsewhere/1"]
