"""A build that ends on a pull request the forge shows merged or closed has it recorded by the
tick, once the build has released the unit's branch lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, RUNNING, SETTLING
from tests.factories import stored_unit
from tests.tick_driver import OTHER, UNIT, make_setup


@pytest.mark.parametrize(("shown", "recorded"), [("merged", SETTLING), ("closed", CLOSED)])
def test_the_tick_records_what_the_forge_showed_after_the_build_released_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shown: str, recorded
) -> None:
    graph = make_setup(tmp_path, monkeypatch)
    graph.store.set_state(UNIT, RUNNING, pr=7, branch=f"spec/{UNIT}")
    graph.options["forge_state"] = lambda unit, pr: shown

    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == recorded
    assert not any("in review" in line for line in graph.recorder.logged), graph.recorder.logged


def test_a_child_of_a_merge_recorded_after_the_build_is_handed_to_the_restack_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = make_setup(tmp_path, monkeypatch)
    graph.store.upsert([stored_unit(OTHER, depends_on=(UNIT,))])
    graph.store.set_state(UNIT, RUNNING, pr=7, branch=f"spec/{UNIT}")
    graph.store.set_state(OTHER, IN_REVIEW, pr=8, branch=f"spec/{OTHER}")
    graph.options["forge_state"] = lambda unit, pr: "merged"
    handed: list[str] = []
    hand_over = RestackLanes.hand_over

    def spy(self, unit, *args, **kwargs):
        handed.append(unit.id)
        return hand_over(self, unit, *args, **kwargs)

    monkeypatch.setattr(RestackLanes, "hand_over", spy)

    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == SETTLING
    assert OTHER in handed, "the child went through the lane, not an inline restack"
