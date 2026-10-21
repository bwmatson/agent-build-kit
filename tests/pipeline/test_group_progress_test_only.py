"""The progress walk over a stubbed build's branch takes one subject for a test-only group and
two for another (spec: test-only-groups)."""

from __future__ import annotations

from agent_build_kit.pipeline.commit_order import GroupProgress, group_progress

TITLES = ["A", "B"]


def test_a_test_only_groups_tests_commit_alone_is_done() -> None:
    progress = group_progress(["test: A", "feat: A", "test: B"], TITLES, [False, True])

    assert progress == GroupProgress(done=2, tests_made=False)


def test_a_test_only_group_is_never_tests_made() -> None:
    before = group_progress(["test: A", "feat: A"], TITLES, [False, True])
    only = group_progress(["test: A"], ["A"], [True])
    none = group_progress([], ["A"], [True])

    assert before == GroupProgress(done=1, tests_made=False)
    assert only == GroupProgress(done=1, tests_made=False)
    assert none == GroupProgress(done=0, tests_made=False)


def test_a_test_only_group_takes_one_subject_and_the_next_group_the_following_two() -> None:
    complete = group_progress(["test: A", "test: B", "feat: B"], TITLES, [True, False])
    unpaired = group_progress(["test: A", "test: B"], TITLES, [True, False])

    assert complete == GroupProgress(done=2, tests_made=False)
    assert unpaired == GroupProgress(done=1, tests_made=True)


def test_a_group_is_judged_by_its_flag_and_without_flags_the_walk_is_as_before() -> None:
    subjects = ["test: A", "feat: A", "test: B"]

    unflagged = group_progress(subjects, TITLES)
    all_false = group_progress(subjects, TITLES, [False, False])
    flagged = group_progress(subjects, TITLES, [False, True])

    assert unflagged == all_false == GroupProgress(done=1, tests_made=True)
    assert flagged == GroupProgress(done=2, tests_made=False)
