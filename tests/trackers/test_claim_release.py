# ruff: noqa: F811 — the imported fixture is requested by name
"""Retiring a unit clears the sync account's claims on its group items; every other unit keeps
its claims."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli.retire_cmd import retire
from tests.retire_scene import Scene, scene  # noqa: F401
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import SYNC, RecordingTracker, World
from tests.trackers.start_support import PERSON

REASON = "narrowed"


@pytest.fixture(autouse=True)
def unregistered() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


class Board:
    """The retire scene with the change's two group items on the board, both claimed by the sync
    account, and the change's tracker file where the scene's planning repo keeps it."""

    def __init__(self, scene: Scene, tmp_path: Path) -> None:
        folder = tmp_path / "board"
        folder.mkdir()
        self.scene = scene
        self.said: list[str] = []
        self.world = World(folder, board_section(["change", "group"]), RecordingTracker())
        self.world.run([covering(f"{CHANGE}/1", (1,)), covering(f"{CHANGE}/2", (2,))])
        shutil.copytree(self.world.change_dir, scene.inst.changes_dir / CHANGE)
        self.items = {group: self.world.item_id(f"{CHANGE}:{group}") for group in (1, 2)}
        for item_id in self.items.values():
            assert self.world.tracker.claim(item_id)

    def assignees(self, group: int) -> tuple[str, ...]:
        return tuple(self.world.tracker.get(self.items[group]).assignees)

    def add(self, uid: str, state: str, groups: tuple[int, ...]) -> None:
        self.scene.add(uid, state, groups=groups, change=CHANGE, branch=False)

    def retire(self, uid: str, *, dry_run: bool = False) -> int:
        def say(text: str, error: bool = False) -> None:
            self.said.append(text)

        return retire(self.scene.inst, uid, say=say, reason=REASON, dry_run=dry_run)


@pytest.fixture
def board(scene: Scene, tmp_path: Path) -> Board:
    return Board(scene, tmp_path)


def test_retire_clears_the_claims_on_every_group_item_the_unit_covers(board: Board) -> None:
    board.add(f"{CHANGE}/1", "planned", (1, 2))

    assert board.retire(f"{CHANGE}/1") == 0

    assert board.assignees(1) == ()
    assert board.assignees(2) == ()


def test_retire_leaves_an_item_a_person_has_since_taken(board: Board) -> None:
    board.add(f"{CHANGE}/1", "planned", (1, 2))
    taken = board.world.tracker.as_identity(PERSON)
    taken.set_assignee(board.items[2], PERSON)

    assert board.retire(f"{CHANGE}/1") == 0

    assert board.assignees(1) == ()
    assert board.assignees(2) == (PERSON,)


@pytest.mark.parametrize("state", ["failed", "held", "merged"])
def test_a_unit_that_is_not_retired_keeps_its_claims(board: Board, state: str) -> None:
    board.add(f"{CHANGE}/1", state, (1,))
    board.add(f"{CHANGE}/2", "planned", (2,))

    assert board.retire(f"{CHANGE}/2") == 0

    assert board.assignees(2) == ()
    assert board.assignees(1) == (SYNC,)


@pytest.mark.parametrize("carrier_state", ["merged", "running"])
def test_a_group_another_unit_carries_keeps_its_claim(board: Board, carrier_state: str) -> None:
    board.add(f"{CHANGE}/1", "planned", (1, 2))
    board.add(f"{CHANGE}/2", carrier_state, (2,))

    assert board.retire(f"{CHANGE}/1") == 0

    assert board.assignees(1) == ()
    assert board.assignees(2) == (SYNC,)


def test_a_dry_run_says_the_claims_would_be_released_and_releases_none(board: Board) -> None:
    board.add(f"{CHANGE}/1", "planned", (1, 2))

    assert board.retire(f"{CHANGE}/1", dry_run=True) == 0

    assert any("release the kit's claims" in line for line in board.said)
    assert board.assignees(1) == (SYNC,)
    assert board.assignees(2) == (SYNC,)
