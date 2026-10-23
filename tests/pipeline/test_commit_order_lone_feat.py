"""`group_progress` names an implementation commit found where its group's tests commit was
expected (spec: built-group-recorded-as-empty-pair)."""

from __future__ import annotations

from agent_build_kit.pipeline.commit_order import group_progress

TITLES = ["A", "B"]


def test_a_feat_of_the_next_group_where_its_test_belongs_is_named_and_nothing_else_is() -> None:
    lone = group_progress(["test: A", "feat: A", "feat: B"], TITLES)
    tests = group_progress(["test: A", "feat: A", "test: B"], TITLES)
    other = group_progress(["test: A", "feat: A", "feat: C"], TITLES)
    test_only = group_progress(["feat: A"], ["A"], [True])

    assert (lone.done, lone.tests_made, lone.lone_feat) == (1, False, "feat: B")
    assert tests.lone_feat == "", "the group's tests commit is there"
    assert other.lone_feat == "", "a feat: with another title is not the group's"
    assert test_only.lone_feat == "", "a test-only group has no feat: to find out of place"
