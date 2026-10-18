"""`inverted_groups` finds each direct edge onto a group less urgent than the group depending on it.

The edges are the planner's chain between a change's groups and the `Needs:` lines, whose
target is read from the other change's tasks file.
"""

from pathlib import Path

from agent_build_kit.pipeline.work_graph import InvertedGroup, inverted_groups
from tests.task_priority_files import group_md, groups_md


def inverted(changes: Path, change: str) -> list[InvertedGroup]:
    return inverted_groups(changes / change / "tasks.md", changes, repos=("app",), projects={})


def write(changes: Path, change: str, *groups: str) -> None:
    (changes / change).mkdir(parents=True, exist_ok=True)
    (changes / change / "tasks.md").write_text(groups_md(*groups))


def pair(
    group: int, priority: int, needed_by: int, by_priority: int, change: str = ""
) -> InvertedGroup:
    return InvertedGroup(
        group=group,
        priority=priority,
        needed_by=needed_by,
        needed_by_priority=by_priority,
        change=change,
    )


def test_a_group_chained_before_a_more_urgent_one_is_returned_with_both_priorities(
    tmp_path: Path,
) -> None:
    write(tmp_path, "feature", group_md(1, 3), group_md(2, 1))

    assert inverted(tmp_path, "feature") == [pair(1, 3, 2, 1)]


def test_a_dependent_at_least_as_urgent_as_what_it_depends_on_returns_nothing(
    tmp_path: Path,
) -> None:
    write(tmp_path, "feature", group_md(1, 1), group_md(2, 1), group_md(3, 2))

    assert inverted(tmp_path, "feature") == []


def test_an_independent_group_has_no_incoming_pair_and_the_next_pairs_with_the_one_before(
    tmp_path: Path,
) -> None:
    write(tmp_path, "feature", group_md(1, 3), group_md(2, 1, independent=True), group_md(3, 1))

    found = inverted(tmp_path, "feature")

    assert pair(1, 3, 2, 1) not in found
    assert found == [pair(1, 3, 3, 1)]


def test_an_acceptance_group_pairs_with_every_earlier_group_at_a_larger_number(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        "feature",
        group_md(1, 3),
        group_md(2, 3),
        group_md(3, 1),
        group_md(4, 1, flag="acceptance"),
    )

    found = inverted(tmp_path, "feature")

    assert pair(1, 3, 4, 1) in found
    assert pair(2, 3, 4, 1) in found
    assert not any(edge.group == 3 and edge.needed_by == 4 for edge in found)


def test_a_needs_line_to_another_changes_group_of_a_larger_number_names_that_change(
    tmp_path: Path,
) -> None:
    write(tmp_path, "other", group_md(1, 3))
    write(tmp_path, "feature", group_md(1, 1, needs="other group 1"))

    assert inverted(tmp_path, "feature") == [pair(1, 3, 1, 1, change="other")]


def test_a_needs_line_to_a_group_of_a_lower_number_returns_nothing(tmp_path: Path) -> None:
    write(tmp_path, "other", group_md(1, 1))
    write(tmp_path, "feature", group_md(1, 3, needs="other group 1"))

    assert inverted(tmp_path, "feature") == []


def test_a_needs_target_missing_from_the_other_change_returns_nothing_and_no_error(
    tmp_path: Path,
) -> None:
    write(tmp_path, "other", group_md(1, 3))
    write(tmp_path, "feature", group_md(1, 1, needs="other group 7"))
    write(tmp_path, "lonely", group_md(1, 1, needs="absent group 1"))

    assert inverted(tmp_path, "feature") == []
    assert inverted(tmp_path, "lonely") == []
