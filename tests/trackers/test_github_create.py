"""Creating and reading GitHub issues as kit items: a level is a type or a label by the owner,
a child is a sub-issue of the item above, and an item is found again by its marker."""

from __future__ import annotations

import re
from typing import Any

import pytest

from agent_build_kit.forges.transport import HostError
from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.github import GithubIssues, SubIssueLimitExceeded
from tests.trackers.github_issue_host import IssueHost
from tests.trackers.github_support import MODE_TYPES, tracker_on

pytestmark = pytest.mark.usefixtures("github_env")

LEVELS: tuple[ItemKind, ...] = ("change", "group", "task")


def create_down_to(tracker: GithubIssues, level: ItemKind) -> Item:
    """A change, group and task made in turn, each under the one above, as far as `level`."""
    parent: str | None = None
    for above in LEVELS:
        made = tracker.create(above, f"{above} item", parent=parent, markers=(f"m-{above}",))
        if above == level:
            return made
        parent = made.id
    raise AssertionError(level)


def test_a_group_item_is_created_as_an_issue_with_the_marker_under_its_change() -> None:
    host = IssueHost()
    change = host.seed("Change")

    item = tracker_on(host).create("group", "Group one", "Do it", change, markers=("feature:g1",))

    assert len(host.creates) == 1
    assert re.search(r"<!--[^>]*feature:g1[^>]*-->", host.creates[0]["body"])
    assert host.sub_issues_of(change) == [item.id]
    assert (item.kind, item.parent_id) == ("group", change)
    assert item.url


def test_a_task_is_nested_under_a_group_and_listed_among_its_children() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    change = tracker.create("change", "Change", markers=("feature",))
    group = tracker.create("group", "Group", parent=change.id, markers=("feature:g1",))

    task = tracker.create("task", "Task", parent=group.id, markers=("feature:g1.t1",))

    assert host.sub_issues_of(group.id) == [task.id]
    assert [(child.id, child.kind) for child in tracker.children(group.id)] == [(task.id, "task")]
    assert [child.id for child in tracker.children(change.id)] == [group.id]


def test_with_two_levels_nothing_is_nested_below_the_groups() -> None:
    host = IssueHost()
    tracker = tracker_on(host, levels=("change", "group"))
    change = tracker.create("change", "Change", markers=("feature",))
    group = tracker.create("group", "Group", parent=change.id, markers=("feature:g1",))

    with pytest.raises(ValueError):
        tracker.create("task", "Task", parent=group.id, markers=("feature:g1.t1",))

    assert host.sub_issues_of(change.id) == [group.id]
    assert host.sub_issues_of(group.id) == []
    assert len(host.issues) == 2


def test_a_skipped_level_attaches_to_the_nearest_level_above() -> None:
    host = IssueHost()
    tracker = tracker_on(host, levels=("change", "task"))
    change = tracker.create("change", "Change", markers=("feature",))

    task = tracker.create("task", "Task", parent=change.id, markers=("feature:g1.t1",))

    assert host.sub_issues_of(change.id) == [task.id]
    assert task.parent_id == change.id


def test_a_created_item_is_found_by_its_marker() -> None:
    host = IssueHost()
    tracker = tracker_on(host)
    made = tracker.create("change", "Change", markers=("add-marker",))

    found = tracker.find_by_marker("add-marker")

    assert found is not None
    assert found.id == made.id
    assert tracker.find_by_marker("other-change") is None


def test_an_item_whose_create_answer_was_lost_is_found_and_not_created_twice() -> None:
    host = IssueHost(lose_create_answer=True)
    tracker = tracker_on(host)

    with pytest.raises(HostError):
        tracker.create("change", "Change", markers=("add-marker",))
    found = tracker.find_by_marker("add-marker")

    assert isinstance(found, Item)
    assert found.title == "Change"
    assert len(host.creates) == 1


def test_a_parent_at_the_sub_issue_limit_is_refused_naming_it_and_the_limit() -> None:
    host = IssueHost(sub_issue_limit=2)
    change = host.seed("Change")
    host.seed("First", parent=change)
    host.seed("Second", parent=change)

    with pytest.raises(SubIssueLimitExceeded) as refused:
        tracker_on(host).create("group", "Third", parent=change, markers=("feature:g3",))

    assert f"#{change}" in str(refused.value)
    assert "2" in str(refused.value)


@pytest.mark.parametrize("level", LEVELS)
def test_an_organization_with_types_uses_the_configured_type_for_each_level(
    level: ItemKind,
) -> None:
    host = IssueHost(owner_kind="Organization", types_enabled=True)
    tracker = tracker_on(host, "organization")

    made = create_down_to(tracker, level)

    issue = host.issues[int(made.id)]
    assert issue["type"]["name"] == MODE_TYPES["organization"][level]
    assert not [label for label in issue["labels"] if label["name"].startswith("abk:")]
    assert tracker.capabilities().typed


@pytest.mark.parametrize(
    "host_options",
    [
        {"owner_kind": "User"},
        {"owner_kind": "Organization", "types_enabled": False},
    ],
    ids=["user owner", "organization without types"],
)
@pytest.mark.parametrize("level", LEVELS)
def test_without_types_each_level_is_a_label(host_options: dict[str, Any], level: ItemKind) -> None:
    host = IssueHost(**host_options)
    tracker = tracker_on(host, "user")

    made = create_down_to(tracker, level)

    issue = host.issues[int(made.id)]
    assert [label["name"] for label in issue["labels"]] == [MODE_TYPES["user"][level]]
    assert issue.get("type") is None
    assert not tracker.capabilities().typed
