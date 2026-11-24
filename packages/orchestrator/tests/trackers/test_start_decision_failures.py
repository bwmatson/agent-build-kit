"""A board, configuration or tracker-file failure is a wait for that unit, never a raise."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.forges.transport import AuthError, HostUnavailable
from agent_build_kit.pipeline.tracker_file import tracker_path
from agent_build_kit.trackers.start_decision import start_decision
from tests.trackers.board_support import CHANGE
from tests.trackers.reconciler_support import Call, World
from tests.trackers.start_support import board
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def failing_on(world: World, name: str) -> None:
    def fail(call: Call) -> Exception | None:
        return HostUnavailable("get", "the board is down", 3) if call.name == name else None

    world.tracker.fail = fail


@pytest.mark.parametrize("name", ["get", "identity"])
def test_a_failing_read_of_the_board_is_a_wait(tmp_path: Path, name: str) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    failing_on(world, name)

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "wait"
    assert "the board is down" in decision.reason


def test_a_refused_credential_is_a_wait(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    world.tracker.fail = lambda call: AuthError("401") if call.name == "get" else None

    assert start_decision(unit, changes_dir=world.changes_dir).outcome == "wait"


def test_a_kind_with_no_tracker_registered_is_a_wait(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    trackers.unregister("azure_devops")

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "wait"
    assert "azure_devops" in decision.reason


def test_an_invalid_section_is_a_wait(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    configure(app={"kind": "azure_devops", "azure_devops": {**AZURE_BLOCK, "types": {}}})

    assert start_decision(unit, changes_dir=world.changes_dir).outcome == "wait"


def test_an_unparsable_tracker_file_is_a_wait(tmp_path: Path) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    tracker_path(world.change_dir).write_text("groups: [unclosed\n")

    assert start_decision(unit, changes_dir=world.changes_dir).outcome == "wait"


def test_a_tracker_file_of_another_board_is_a_wait_and_its_ids_are_not_read(
    tmp_path: Path,
) -> None:
    world, unit = board(tmp_path, ["change", "group"])
    path = tracker_path(world.change_dir)
    path.write_text(path.read_text().replace("azure_devops", "other_board", 1))
    world.tracker.calls.clear()

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "wait"
    assert CHANGE in decision.reason
    assert world.tracker.made("get") == []
