"""The inbound poll: a cursor, the kit's own writes ignored, a first poll that only records and
a backoff after failures (spec: tracker-pull)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.trackers.base import Change, Cursor
from agent_build_kit.trackers.poll import poll_board
from tests import fake_clock
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import RecordingTracker, World
from tests.trackers.tracker_section_support import configure

PERSON = "alice"
GROUP = f"{CHANGE}:1"


class ReadCounting(RecordingTracker):
    """The recording stand-in that also records, and may fail, the poll's read."""

    def changed_since(self, cursor: Cursor | None) -> tuple[Sequence[Change], Cursor]:
        self._enter("changed_since", cursor)
        return super().changed_since(cursor)


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def world(tmp_path: Path, clock: fake_clock.FakeClock) -> World:
    made = World(tmp_path, board_section(["change", "group"]), ReadCounting())
    made.run()
    return made


def poll(world: World) -> tuple[Change, ...]:
    return poll_board("app", state_dir=world.state_dir, log=world.logs.append)


def person_assigns(world: World, marker: str) -> str:
    item_id = world.item_id(marker)
    world.tracker.as_identity(PERSON).set_assignee(item_id, PERSON)
    return item_id


def test_a_persons_change_is_reported_once_over_two_polls(world: World) -> None:
    assert poll(world) == ()  # the first poll only records
    item_id = person_assigns(world, GROUP)

    first = poll(world)
    second = poll(world)

    assert [(change.item_id, change.who) for change in first] == [(item_id, PERSON)]
    assert second == ()


def test_the_kits_own_write_is_ignored_by_its_recorded_revision(world: World) -> None:
    poll(world)
    item_id = world.item_id(GROUP)
    revision = world.tracker.get(item_id).revision

    world.run([covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)])  # the kit moves the group item

    assert world.tracker.get(item_id).revision != revision
    assert poll(world) == ()


def test_a_persons_change_after_the_kits_write_is_still_reported(world: World) -> None:
    poll(world)
    world.run([covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)])
    item_id = person_assigns(world, GROUP)

    assert [change.item_id for change in poll(world)] == [item_id]


def test_the_first_poll_after_a_restart_records_and_applies_nothing(world: World) -> None:
    person_assigns(world, GROUP)  # on the board before this machine ever polled

    assert poll(world) == ()

    later = person_assigns(world, CHANGE)
    assert [change.item_id for change in poll(world)] == [later]


def test_two_failed_polls_back_the_next_off_until_the_interval_has_passed(
    world: World, clock: fake_clock.FakeClock
) -> None:
    poll(world)
    world.tracker.fail = lambda call: (
        HostUnavailable("changed_since", "down", 3) if call.name == "changed_since" else None
    )
    poll(world)
    poll(world)
    reads = len(world.tracker.made("changed_since"))
    world.tracker.fail = lambda call: None
    item_id = person_assigns(world, GROUP)

    clock.advance(60)
    assert poll(world) == ()
    assert len(world.tracker.made("changed_since")) == reads

    clock.advance(24 * 3600)
    assert [change.item_id for change in poll(world)] == [item_id]
    assert world.logs


def test_with_no_tracker_section_the_step_makes_no_call(tmp_path: Path) -> None:
    watched = ReadCounting()
    built: list[object] = []
    section = board_section(["change", "group"])
    trackers.register(section.kind, lambda _section: built.append(1) or watched)
    configure(app=None)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    assert poll_board("app", state_dir=state_dir) == ()

    assert not built
    assert not watched.calls
    assert not list(state_dir.iterdir())
