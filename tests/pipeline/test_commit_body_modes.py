"""The implementation commit of a group with no tests step does not say the previous commit's
tests now pass (spec: group-build-modes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.commit_body import commit_body
from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.stack_runner import GroupStep

GOAL = "Done when the guide names the setting."
PREVIOUS = "tests of the previous commit"


def step(mode: GroupMode) -> GroupStep:
    return GroupStep(
        change_dir=str(Path("changes") / "feature"), number=1, title="G1", goal=GOAL, mode=mode
    )


@pytest.mark.parametrize("mode", [GroupMode.NO_CODE, GroupMode.REFACTOR])
def test_a_group_with_no_tests_step_keeps_its_goal_and_drops_the_tests_sentence(
    mode: GroupMode,
) -> None:
    body = commit_body([step(mode)], tests=False)

    assert GOAL in body
    assert PREVIOUS not in body


def test_a_group_with_a_tests_step_still_says_its_tests_now_pass() -> None:
    body = commit_body([step(GroupMode.TESTS_AND_CODE)], tests=False)

    assert PREVIOUS in body
