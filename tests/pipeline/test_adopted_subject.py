"""`adopted_subject` is the subject the next commit of a unit's branch must have to be counted
by `group_progress`, so a commit the pipeline makes for a person follows the convention
(spec: attach-commit-subject)."""

from __future__ import annotations

from agent_build_kit.pipeline.commit_order import adopted_subject, group_progress
from agent_build_kit.pipeline.stack_runner import GroupStep

UNIT_TITLE = "Add the marker"


def steps(*titles: str, test_only: tuple[int, ...] = ()) -> tuple[GroupStep, ...]:
    return tuple(
        GroupStep(change_dir="changes/feature", number=n, title=title, test_only=n in test_only)
        for n, title in enumerate(titles, start=1)
    )


def subject(groups: tuple[GroupStep, ...], branch: list[str]) -> str:
    return adopted_subject(UNIT_TITLE, groups, branch)


def test_a_two_group_unit_is_asked_for_each_commit_in_turn() -> None:
    groups = steps("Parse", "Use")

    assert subject(groups, []) == "test: Parse"
    assert subject(groups, ["test: Parse"]) == "feat: Parse"
    assert subject(groups, ["test: Parse", "feat: Parse"]) == "test: Use"
    assert subject(groups, ["test: Parse", "feat: Parse", "test: Use"]) == "feat: Use"


def test_a_unit_whose_groups_all_have_their_commits_gets_a_fix_naming_the_last_group() -> None:
    groups = steps("Parse", "Use")
    branch = ["test: Parse", "feat: Parse", "test: Use", "feat: Use"]

    assert subject(groups, branch) == "fix: Use (adopted)"


def test_a_test_only_group_takes_a_tests_subject_alone() -> None:
    groups = steps("Drive", "Use", test_only=(1,))

    assert subject(groups, []) == "test: Drive"
    assert subject(groups, ["test: Drive"]) == "test: Use"
    assert subject(steps("Drive", test_only=(1,)), ["test: Drive"]) == "fix: Drive (adopted)"


def test_two_groups_with_one_title_are_told_apart_by_position() -> None:
    groups = steps("Same", "Same")

    assert subject(groups, ["test: Same"]) == "feat: Same"
    assert subject(groups, ["test: Same", "feat: Same"]) == "test: Same"
    assert subject(groups, ["test: Same", "feat: Same", "test: Same"]) == "feat: Same"
    assert subject(groups, ["test: Same", "feat: Same", "test: Same", "feat: Same"]) == (
        "fix: Same (adopted)"
    )


def test_an_unstubbed_unit_gets_the_units_title_and_a_fix_once_it_has_a_commit() -> None:
    assert subject((), []) == f"feat: {UNIT_TITLE}"
    assert subject((), ["whatever the commit says"]) == f"fix: {UNIT_TITLE} (adopted)"


def test_the_subject_given_is_the_one_the_counter_accepts_as_the_next() -> None:
    groups = steps("Parse", "Use")
    titles = [group.title for group in groups]
    branch: list[str] = []

    for _ in range(4):
        branch.append(subject(groups, branch))

    assert group_progress(branch, titles).done == len(titles)
