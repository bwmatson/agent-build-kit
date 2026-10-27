"""A hold is released by hand, and not once it is done (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.external_file import (
    DONE,
    RELEASED,
    HoldRefused,
    add_hold,
    read_holds,
    release_hold,
)
from tests.external_support import hold, waits_of, world_of
from tests.factories import stored_unit


def test_release_clears_a_held_hold_and_the_unit_is_considered_next_tick(tmp_path: Path) -> None:
    inst, store, folder = world_of(tmp_path, stored_unit("feature/1", change="feature"))
    add_hold(folder, hold((1,)))
    assert waits_of(inst, store)["feature/1"].reason.value == "external"

    release_hold(folder, 1)

    assert [h.status for h in read_holds(folder)] == [RELEASED]
    assert waits_of(inst, store)["feature/1"].reason.value == "ready"


def test_release_names_the_hold_by_any_group_it_covers(tmp_path: Path) -> None:
    _inst, _store, folder = world_of(tmp_path)
    add_hold(folder, hold((2, 3)))

    release_hold(folder, 3)

    assert [h.status for h in read_holds(folder)] == [RELEASED]


def test_a_done_hold_cannot_be_released(tmp_path: Path) -> None:
    _inst, _store, folder = world_of(tmp_path)
    add_hold(folder, hold((1,), status=DONE))

    with pytest.raises(HoldRefused, match="done"):
        release_hold(folder, 1)

    assert [h.status for h in read_holds(folder)] == [DONE]


def test_a_group_nobody_holds_cannot_be_released(tmp_path: Path) -> None:
    _inst, _store, folder = world_of(tmp_path)

    with pytest.raises(HoldRefused, match="group 1"):
        release_hold(folder, 1)
