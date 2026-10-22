"""An ordinary plan of a change is given the pins of its superseded units whose pieces have not
started, and is refused if it ignores them (spec: split-planning, a later plan keeps the pins)."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.replan_driver import Replan, answer, planned
from tests.split_step_support import HELD_ID, PIECES, correct, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"
PINS = re.compile(r"\bpin", re.IGNORECASE)


def split(run: Replan) -> None:
    """The held unit split into its pieces, which are all planned."""
    run.runtime.answer = reply(*correct())
    cli.split_held_units(run.inst, run.store)
    run.runtime.requests.clear()


def tiered(uid: str, groups: tuple[int, ...], tier: str, after: tuple[str, ...] = ()) -> dict:
    return {**planned(uid, groups, depends_on=after), "review_tier": tier}


def regrouped() -> str:
    """A plan that puts the pinned group 3 beside group 2."""
    return answer(
        tiered("feature/1", (1,), "auto", ("base/1",)),
        tiered("feature/2", (2, 3), "full", ("feature/1",)),
        tiered("feature/4", (4, 5), "auto", ("feature/2",)),
        tiered("feature/6", (6,), "auto", ("feature/4",)),
    )


def kept() -> str:
    """A plan that keeps the pinned group 3 in a unit of its own at the earned tier."""
    return answer(
        tiered("feature/1", (1, 2), "auto", ("base/1",)),
        tiered("feature/3", (3,), "full", ("feature/1",)),
        tiered("feature/4", (4, 5), "auto", ("feature/3",)),
        tiered("feature/6", (6,), "auto", ("feature/4",)),
    )


def test_a_plan_is_given_the_pins_of_a_superseded_unit_whose_pieces_have_not_started(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    split(run)
    run.runtime.answer = kept()

    result = cli.plan_all(run.inst, store=run.store, force=True)[CHANGE]

    assert result.status == "planned"
    assert PINS.search(run.runtime.requests[0].prompt)
    assert HELD_ID in run.runtime.requests[0].prompt


def test_a_plan_that_regroups_the_driver_is_refused_and_leaves_no_accepted_record(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    split(run)
    before = run.store.all()
    run.runtime.answer = regrouped()

    result = cli.plan_all(run.inst, store=run.store, force=True)[CHANGE]

    assert result.status == "failed"
    assert run.records[CHANGE]["ok"] is False
    assert run.store.all() == before


def test_the_record_of_an_accepted_plan_is_written_ok(tmp_path, monkeypatch) -> None:
    run = scene(tmp_path, monkeypatch)
    split(run)
    run.runtime.answer = kept()

    cli.plan_all(run.inst, store=run.store, force=True)

    assert run.records[CHANGE]["ok"] is True
    assert PINS.search(run.runtime.requests[0].prompt), "accepted under the pins"


def test_pieces_that_have_started_are_given_no_pins(tmp_path, monkeypatch) -> None:
    run = scene(tmp_path, monkeypatch)
    split(run)
    run.runtime.answer = kept()
    cli.plan_all(run.inst, store=run.store, force=True)
    assert PINS.search(run.runtime.requests[0].prompt), "unstarted pieces are pinned"
    for number, uid in enumerate(PIECES, start=1):
        run.store.set_state(uid, IN_REVIEW, branch=f"spec/{uid}", pr=20 + number)
    run.runtime.requests.clear()
    run.runtime.answer = answer(tiered("feature/6", (6,), "auto", (PIECES[-1],)))

    result = cli.plan_all(run.inst, store=run.store, force=True)[CHANGE]

    assert result.status == "planned"
    assert not PINS.search(run.runtime.requests[0].prompt)
