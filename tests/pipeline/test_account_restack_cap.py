"""An account's `max_concurrent_resolutions` caps the restacks of that account running at once
across its projects, beside each project's own cap (spec: account-project-limits).

`slot_restack_limit(inst)` reads the cap from the accounts that set the field, and the tick's
lanes (`build_restack_lane`) hold their restacks to it: an account that does not set it, and the
default account, add no cap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.resolution_lane import ResolutionLane
from agent_build_kit.pipeline.slots import slot_of, slot_restack_limit
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.pipeline.test_limits_for import installation
from tests.restack_lane_fakes import WAIT, Restacks
from tests.restack_lanes_fakes import API, DOCS, WEB, unit_of

# `app` runs on the account `kit`; `platform` on the default account.
ON_KIT = {"app": "kit"}


def kit(tmp_path: Path, **limits: int) -> Installation:
    return installation(tmp_path, accounts={"kit": {"project_limits": limits}}, labels=ON_KIT)


def test_an_account_that_sets_the_cap_has_it_for_its_slot(tmp_path: Path) -> None:
    inst = kit(tmp_path, max_concurrent_resolutions=1)

    assert slot_restack_limit(inst)("kit") == 1


def test_an_account_that_sets_other_limits_only_has_no_restack_cap(tmp_path: Path) -> None:
    inst = kit(tmp_path, max_concurrent_stacks=2)

    assert slot_restack_limit(inst)("kit") is None


def test_the_default_account_has_no_restack_cap(tmp_path: Path) -> None:
    inst = kit(tmp_path, max_concurrent_resolutions=1)

    assert slot_restack_limit(inst)(None) is None


def test_installations_with_no_account_have_no_restack_cap_for_any_slot(tmp_path: Path) -> None:
    inst = installation(tmp_path, project={"max_concurrent_resolutions": 1}, labels={})

    assert slot_restack_limit(inst)(WEB) is None
    assert slot_restack_limit(inst)(None) is None


def test_the_cap_is_the_one_the_account_set_not_the_project_value(tmp_path: Path) -> None:
    inst = installation(
        tmp_path,
        project={"max_concurrent_resolutions": 4},
        accounts={"kit": {"project_limits": {"max_concurrent_resolutions": 3}}},
        labels=ON_KIT,
    )

    assert slot_restack_limit(inst)("kit") == 3
    assert inst.max_concurrent_resolutions == 4


class Scene:
    """The tick's lanes over an installation, with each lane's restack the fake `restacks` makes
    in place of the real move, so what runs beside what is read from the events."""

    def __init__(self, tmp_path: Path, inst: Installation, monkeypatch: pytest.MonkeyPatch) -> None:
        self.restacks = Restacks()
        locks = tmp_path / "locks"
        self.made: list[ResolutionLane] = []
        restacks = self.restacks

        def lane(cap: int, **kwargs: Any) -> ResolutionLane:
            made = ResolutionLane(
                cap,
                move=restacks,
                claim=build_claim(locks),
                paused=kwargs["paused"],
                base=kwargs["base"],
                runs=kwargs["runs"],
            )
            self.made.append(made)
            return made

        monkeypatch.setattr(cli, "ResolutionLane", lane)
        self.lanes = cli.build_restack_lane(inst, UnitStore(tmp_path / "units.json"))

    def hand_over(self, number: int, key: Any) -> None:
        self.lanes.hand_over(unit_of(number, key))

    def begun(self, number: int) -> bool:
        return self.restacks.begun[f"feature/{number}"].wait(WAIT)

    def close(self) -> None:
        self.restacks.release_all()
        self.lanes.drain()


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Scene]]:
    """Makes a `Scene` over the account `kit` with the project limits given; every scene made is
    closed after the test, so no restack outlives it."""
    made: list[Scene] = []

    def build(**limits: int) -> Scene:
        made.append(Scene(tmp_path, kit(tmp_path, **limits), monkeypatch))
        return made[-1]

    yield build
    for each in made:
        each.close()


def test_the_ticks_lanes_run_one_restack_of_a_one_restack_account_across_its_projects(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_resolutions=1)

    ticks.hand_over(1, WEB)
    assert ticks.begun(1)
    ticks.hand_over(2, API)

    assert ticks.lanes.running == ["feature/1"]
    assert ticks.lanes.waiting == ["feature/2"]


def test_the_waiting_restack_starts_when_the_ticks_running_one_ends(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_resolutions=1)
    ticks.hand_over(1, WEB)
    ticks.hand_over(2, API)
    assert ticks.begun(1)

    ticks.restacks.release("feature/1")

    assert ticks.begun(2)


def test_the_ticks_lanes_hold_each_project_to_its_own_cap_under_a_roomy_account(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_resolutions=9)
    for number in (1, 2, 3):
        ticks.hand_over(number, WEB)
    assert ticks.begun(2)

    assert sorted(ticks.lanes.running) == ["feature/1", "feature/2"]
    assert ticks.lanes.waiting == ["feature/3"]


def test_the_ticks_lanes_add_no_cap_for_an_account_that_does_not_set_one(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_stacks=1)
    ticks.hand_over(1, WEB)
    ticks.hand_over(2, API)

    assert ticks.begun(1)
    assert ticks.begun(2)
    assert ticks.lanes.waiting == []


def test_the_ticks_lanes_add_no_cap_for_the_default_account(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_resolutions=1)
    ticks.hand_over(1, WEB)
    assert ticks.begun(1)

    ticks.hand_over(2, DOCS)

    assert ticks.begun(2)
    assert sorted(ticks.lanes.running) == ["feature/1", "feature/2"]


def test_the_ticks_lanes_say_when_an_account_is_at_its_cap(
    scene: Callable[..., Scene],
) -> None:
    ticks = scene(max_concurrent_resolutions=1)
    assert not ticks.lanes.at_cap(unit_of(2, API))
    ticks.hand_over(1, WEB)
    assert ticks.begun(1)

    assert ticks.lanes.account_full(unit_of(2, API))
    assert ticks.lanes.at_cap(unit_of(2, API))
    assert not ticks.lanes.at_cap(unit_of(3, DOCS))


def test_the_ticks_account_slot_is_the_one_the_stack_caps_count_under(tmp_path: Path) -> None:
    inst = kit(tmp_path, max_concurrent_resolutions=1)

    assert slot_of(inst)(unit_of(1, WEB)) == "kit"
    assert slot_of(inst)(unit_of(1, DOCS)) is None
