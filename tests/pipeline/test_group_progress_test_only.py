"""The progress walk over a stubbed build's branch takes one subject for a test-only group and
two for another (spec: test-only-groups)."""

from __future__ import annotations

from agent_build_kit.pipeline.commit_order import GroupProgress, group_progress
from agent_build_kit.pipeline.group_mode import GroupMode

TITLES = ["A", "B"]
CODE, ONLY = GroupMode.TESTS_AND_CODE, GroupMode.TESTS_ONLY


def test_a_test_only_groups_tests_commit_alone_is_done() -> None:
    progress = group_progress(["test: A", "feat: A", "test: B"], TITLES, [CODE, ONLY])

    assert progress == GroupProgress(done=2, tests_made=False)


def test_a_test_only_group_is_never_tests_made() -> None:
    before = group_progress(["test: A", "feat: A"], TITLES, [CODE, ONLY])
    only = group_progress(["test: A"], ["A"], [ONLY])
    none = group_progress([], ["A"], [ONLY])

    assert before == GroupProgress(done=1, tests_made=False)
    assert only == GroupProgress(done=1, tests_made=False)
    assert none == GroupProgress(done=0, tests_made=False)


def test_a_test_only_group_takes_one_subject_and_the_next_group_the_following_two() -> None:
    complete = group_progress(["test: A", "test: B", "feat: B"], TITLES, [ONLY, CODE])
    unpaired = group_progress(["test: A", "test: B"], TITLES, [ONLY, CODE])

    assert complete == GroupProgress(done=2, tests_made=False)
    assert unpaired == GroupProgress(done=1, tests_made=True)


def test_a_group_is_judged_by_its_mode_and_without_modes_the_walk_is_as_before() -> None:
    subjects = ["test: A", "feat: A", "test: B"]

    unmoded = group_progress(subjects, TITLES)
    all_code = group_progress(subjects, TITLES, [CODE, CODE])
    moded = group_progress(subjects, TITLES, [CODE, ONLY])

    assert unmoded == all_code == GroupProgress(done=1, tests_made=True)
    assert moded == GroupProgress(done=2, tests_made=False)
