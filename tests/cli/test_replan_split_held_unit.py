"""A unit parked on a held split stays parked across a replan and is released with the split."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import remove_hold
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit
from tests.parked_split_support import Deliveries, hold, installation, park, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "feature/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=None)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = store_of(inst)
    park(store, splits=("acp",))
    return store


def check_still_parked(store: UnitStore) -> None:
    parked = store.get(UNIT)
    assert parked.state == PLANNED
    assert (parked.cause, parked.parked_splits, parked.parked_sha) == (
        Cause.SPLIT_HELD,
        ["acp"],
        "abc1234",
    )


def test_a_replan_does_not_release_a_unit_while_its_split_is_held_and_it_is_after(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Deliveries(monkeypatch)
    hold(inst, "acp")

    store.upsert([unit(UNIT, change="feature")], change="feature")
    cli.release_split_held(inst, store)
    check_still_parked(store)

    store.upsert([], change="feature")
    store.upsert([unit(UNIT, change="feature")], change="feature")
    cli.release_split_held(inst, store)
    check_still_parked(store)
    assert thread.delivered == []

    assert remove_hold(inst.state_dir, "acp")
    cli.release_split_held(inst, store)

    assert thread.delivered == [(UNIT, "requeue")]
