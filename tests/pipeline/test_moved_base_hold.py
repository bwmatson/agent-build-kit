"""A unit whose moved-base runs at one tip did not settle it is held, for a person
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config
from tests.moved_base_attempts_scene import Attempts

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
