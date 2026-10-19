"""A new split that is held defers the rework, and releasing the old split does not resume the
unit onto tests the plan has moved (spec: a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import remove_hold
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.parked_split_support import hold, installation, park, store_of
from tests.split_changed_support import UNIT, Reworks, release, write_split

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=None, claude_code=None, gpu=None)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = store_of(inst)
    park(store, splits=("acp",), split="acp")
    return store


def a_round(inst: Installation, store: UnitStore) -> None:
    """The steps of a pass that act on a parked unit, in the tick's order."""
    release(inst, store)
    cli.release_split_held(inst, store)


def test_a_new_split_that_is_held_defers_until_it_is_released_and_the_old_release_does_not_resume(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "gpu")
    hold(inst, "acp")
    hold(inst, "gpu")
    parked = store.get(UNIT)

    a_round(inst, store)
    assert thread.calls == [] and store.get(UNIT) == parked, "both held"

    assert remove_hold(inst.state_dir, "acp")
    a_round(inst, store)
    assert thread.calls == [] and store.get(UNIT) == parked, "the old split is not the new one"

    assert remove_hold(inst.state_dir, "gpu")
    a_round(inst, store)
    [call] = thread.calls
    assert call["reason"] == "its group's Split changed from acp to gpu"
    assert "acp" in call["guidance"] and "gpu" in call["guidance"]
    assert store.get(UNIT).split == "gpu"

    a_round(inst, store)
    assert len(thread.calls) == 1, "once"


def test_a_new_split_released_while_the_old_is_still_held_is_reworked(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "gpu")
    hold(inst, "acp")

    a_round(inst, store)

    assert [call["unit"] for call in thread.calls] == [UNIT]


def test_a_group_changed_to_rest_which_is_never_held_is_reworked_in_the_first_pass(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "rest")
    hold(inst, "acp")

    a_round(inst, store)

    [call] = thread.calls
    assert call["reason"] == "its group's Split changed from acp to rest"
    assert store.get(UNIT).split == "rest"
