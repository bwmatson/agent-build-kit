"""A unit whose moved-base runs at one tip did not settle it is held, for a person
(spec: unit-scheduling)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from tests.moved_base_attempts_scene import BRANCH, UNIT, Attempts

pytestmark = pytest.mark.usefixtures("scripted_engine")

ROUNDS = 3  # `global_limits.max_review_rounds`, as the fixture installation has it


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Attempts:
    scene = Attempts(tmp_path, monkeypatch)
    assert config.active().global_limits.max_review_rounds == ROUNDS
    scene.ends = scene.stands
    return scene


def three_runs_end_with_the_conflict_standing(scene: Attempts) -> None:
    for _ in range(ROUNDS):
        scene.run_again()


def test_three_runs_that_leave_the_conflict_standing_hold_the_unit_with_a_note(
    scene: Attempts,
) -> None:
    three_runs_end_with_the_conflict_standing(scene)
    assert scene.unit.state == PLANNED

    scene.run_again()

    stored = scene.unit
    assert (stored.state, stored.held_by, stored.cause) == (
        HELD,
        HeldBy.REVIEW,
        Cause.NEEDS_HUMAN,
    )
    note = stored.history[-1]["note"]
    assert "main" in note
    assert scene.tip()[:12] in note
    assert f"{ROUNDS} attempts" in note
    assert re.search(r"restack[ _]conflict", note), "how the last run ended"


def test_the_lane_does_not_start_a_run_after_the_attempts_are_spent(scene: Attempts) -> None:
    three_runs_end_with_the_conflict_standing(scene)

    scene.run_again()
    scene.run_again()

    assert len(scene.ran) == ROUNDS
    assert scene.unit.state == HELD
    assert scene.unit.conflict_attempts == ROUNDS


def test_a_base_that_moves_often_with_each_move_settled_by_one_run_holds_nothing(
    scene: Attempts,
) -> None:
    scene.ends = scene.settles

    for _ in range(ROUNDS + 1):
        scene.base_moves()
        scene.run_again()

    assert len(scene.ran) == ROUNDS + 1
    assert (scene.unit.state, scene.unit.conflict_attempts) == (IN_REVIEW, 1)


def test_a_release_makes_the_unit_owed_again_with_the_count_kept_for_the_tip(
    scene: Attempts,
) -> None:
    three_runs_end_with_the_conflict_standing(scene)
    scene.run_again()
    assert scene.unit.state == HELD

    scene.store.set_state(UNIT, PLANNED, cause=Cause.BASE_CHANGED, branch=BRANCH)

    assert UNIT in cli.owed_units(scene.inst, scene.store.all())
    assert scene.unit.conflict_attempts == ROUNDS
    assert scene.unit.conflict_tip == scene.tip()
