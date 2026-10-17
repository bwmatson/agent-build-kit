"""Only the count decides for the lane whether attempts are spent; the pushed head does not
(spec: unit-scheduling)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import PLANNED
from tests.moved_base_attempts_scene import PUSHED, UNIT, Attempts

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_lane_run_that_changes_nothing_and_ends_planned_is_not_spent_by_the_pushed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Attempts(tmp_path, monkeypatch)
    scene.ends = scene.stands
    scene.store.record_conflict_attempt(
        UNIT, tip=scene.tip(), head=PUSHED, attempts=1, at=datetime.now(UTC)
    )

    scene.scan()
    scene.run_again()

    stored = scene.unit
    assert scene.ran == [UNIT, UNIT], "the pushed head is the recorded head, and the lane runs"
    assert (stored.state, stored.conflict_attempts) == (PLANNED, 3)
    assert stored.attempts_spent(99), "the conflict handler's own rule reads the head as before"
