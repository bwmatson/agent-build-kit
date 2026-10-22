"""A unit requeued behind an unmet parent still waits after a replan, and is delivered once."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from tests.factories import unit
from tests.parked_split_support import Deliveries, installation, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")

PARENT = "dep/1"
CHILD = "feature/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=False)


def plan() -> list:
    return [unit(PARENT, change="dep"), unit(CHILD, change="feature", depends_on=(PARENT,))]


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = store_of(inst)
    store.upsert(plan())
    store.set_state(CHILD, PLANNED, branch=f"spec/{CHILD}", cause=Cause.GATED)
    store.set_gated_requeue(CHILD, RequeueReason.RESUME)
    return store


def test_a_gated_unit_still_waits_after_a_replan_and_is_delivered_once_the_parent_is_merged(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Deliveries(monkeypatch)

    store.upsert(plan()[:1], change="feature")
    store.upsert(plan(), change="feature")

    kept = store.get(CHILD)
    assert (kept.cause, kept.gated_requeue) == (Cause.GATED, RequeueReason.RESUME)
    cli.release_gated(inst, store)
    assert thread.delivered == [], "the parent is not in review"

    store.set_state(PARENT, IN_REVIEW, pr=3)
    cli.release_gated(inst, store)
    assert thread.delivered == [], "in review is not enough"

    store.set_state(PARENT, MERGED, pr=3)
    cli.release_gated(inst, store)
    cli.release_gated(inst, store)

    assert thread.delivered == [(CHILD, "requeue")]
