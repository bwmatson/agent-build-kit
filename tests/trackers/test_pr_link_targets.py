"""The board items a merged unit's pull request attaches to follow `pr_links` and the levels."""

from __future__ import annotations

from collections import Counter

from agent_build_kit.trackers.levels import link_targets

TWO = ("change", "group")
THREE = ("change", "group", "task")


def test_the_default_on_two_levels_gives_the_group_item_of_each_built_group() -> None:
    found = link_targets(TWO, "lowest", "feature", {1: (1, 2), 2: (1,)})

    assert sorted(found) == ["feature:1", "feature:2"]


def test_the_default_on_three_levels_gives_the_task_items_of_the_built_group() -> None:
    found = link_targets(THREE, "lowest", "feature", {3: (1, 2)})

    assert sorted(found) == ["feature:3.1", "feature:3.2"]


def test_the_default_on_the_single_level_change_gives_the_change_item() -> None:
    assert link_targets(("change",), "lowest", "feature", {1: (1,), 2: (1,)}) == ("feature",)


def test_all_gives_every_level_in_use_for_the_groups_with_the_change_item_once() -> None:
    found = link_targets(THREE, "all", "feature", {1: (1,), 2: (1, 2)})

    assert Counter(found) == Counter(
        ["feature", "feature:1", "feature:2", "feature:1.1", "feature:2.1", "feature:2.2"]
    )


def test_all_on_two_levels_gives_the_change_item_once_and_the_group_items() -> None:
    found = link_targets(TWO, "all", "feature", {1: (1,), 2: (1,)})

    assert Counter(found) == Counter(["feature", "feature:1", "feature:2"])


def test_a_list_gives_those_entities_only() -> None:
    assert link_targets(TWO, ("change",), "feature", {1: (1,), 2: (1,)}) == ("feature",)
    assert sorted(link_targets(THREE, ("group", "task"), "feature", {1: (1,)})) == [
        "feature:1",
        "feature:1.1",
    ]


def test_the_manual_epic_is_never_a_target() -> None:
    for setting in ("lowest", "all", ("change",)):
        found = link_targets(TWO, setting, "feature", {1: (1,)})

        assert found
        assert not any("epic" in key for key in found)
