"""The item keys of groups and tasks, one format for the work graph and the link targets."""

from __future__ import annotations

from agent_build_kit.trackers.levels import group_key, task_group_key, task_key


def test_group_and_task_keys_nest() -> None:
    assert group_key("feature", 2) == "feature:2"
    assert task_key("feature", 2, 3) == "feature:2.3"


def test_a_task_key_gives_back_its_group_key() -> None:
    assert task_group_key(task_key("feature", 2, 3)) == group_key("feature", 2)
