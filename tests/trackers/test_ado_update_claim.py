"""Conditional updates, assignment and claim on Azure DevOps work items: an update carries a
test of the revision, a claim reports whether it won, states map from the configuration and
the blocked and in-review markers are tags."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.base import StaleRevision
from tests.trackers.ado_support import section
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

SYNC = "sync@example.com"
OTHER = "other@example.com"


def tracker_on(
    host: WorkItemHost, process: str = "basic", **overrides: Any
) -> AzureDevOpsWorkItems:
    return AzureDevOpsWorkItems(section(process, **overrides), http=host)


def field(host: WorkItemHost, item_id: str, name: str) -> object:
    return host.items[int(item_id)]["fields"][name]


def tags_of(host: WorkItemHost, item_id: str) -> set[str]:
    raw = str(field(host, item_id, "System.Tags"))
    return {tag.strip() for tag in raw.split(";") if tag.strip()}


def assignee(host: WorkItemHost, item_id: str) -> object:
    person = field(host, item_id, "System.AssignedTo")
    return person["uniqueName"] if isinstance(person, dict) else person


@pytest.mark.parametrize("status", [409, 412])
def test_a_stale_revision_is_refused_and_changes_nothing(status: int) -> None:
    host = WorkItemHost(conflict_status=status)
    group = host.seed("Task", "Group")
    tracker = tracker_on(host)
    read_at = tracker.get(group).revision
    host.edit(group, title="Theirs")
    held = host.items[int(group)]["rev"]

    with pytest.raises(StaleRevision):
        tracker.update(group, {"title": "Mine"}, expected_revision=read_at)

    assert field(host, group, "System.Title") == "Theirs"
    assert host.items[int(group)]["rev"] == held


def test_a_fresh_revision_succeeds_and_returns_the_new_one() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group")
    tracker = tracker_on(host)
    read = tracker.get(group)

    updated = tracker.update(group, {"title": "Mine"}, expected_revision=read.revision)

    assert updated.title == "Mine"
    assert field(host, group, "System.Title") == "Mine"
    assert updated.revision == str(host.items[int(group)]["rev"])
    assert updated.revision != read.revision
    patch = host.calls("PATCH", f"wit/workitems/{group}")[-1].body
    assert patch[0] == {"op": "test", "path": "/rev", "value": int(read.revision)}


def test_the_identity_is_the_authenticated_user() -> None:
    host = WorkItemHost()

    assert tracker_on(host).identity().name == SYNC


def test_an_unassigned_group_item_is_claimed() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group")
    tracker = tracker_on(host)

    assert tracker.claim(group) is True

    assert assignee(host, group) == SYNC
    assert tracker.get(group).assignees == (SYNC,)


def test_a_group_item_assigned_elsewhere_in_the_meantime_is_not_held() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group")
    host.race(group, assigned_to=OTHER)

    assert tracker_on(host).claim(group) is False

    assert assignee(host, group) == OTHER


def test_a_group_item_already_assigned_to_someone_else_is_not_held() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group", assigned_to=OTHER)

    assert tracker_on(host).claim(group) is False

    assert assignee(host, group) == OTHER


def test_an_assignment_with_a_stale_revision_is_refused_and_changes_nothing() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group")
    tracker = tracker_on(host)
    read_at = tracker.get(group).revision
    host.edit(group, assigned_to=OTHER)

    with pytest.raises(StaleRevision):
        tracker.set_assignee(group, SYNC, expected_revision=read_at)

    assert assignee(host, group) == OTHER


@pytest.mark.parametrize("tag", ["blocked", "in-review"])
def test_the_markers_are_tags_added_and_removed_with_the_state_unchanged(tag: str) -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group", state="Doing", tags="abk:feature:g1")
    tracker = tracker_on(host)

    added = tracker.set_tag(group, tag, True)

    assert tags_of(host, group) == {"abk:feature:g1", tag}
    assert added.state == "Doing"

    removed = tracker.set_tag(group, tag, False)

    assert tags_of(host, group) == {"abk:feature:g1"}
    assert removed.state == "Doing"
    assert field(host, group, "System.State") == "Doing"


def test_a_marker_already_present_is_not_added_twice() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group", tags="blocked")

    tracker_on(host).set_tag(group, "blocked", True)

    assert str(field(host, group, "System.Tags")).count("blocked") == 1


def test_agile_defaults_map_active_for_a_user_story() -> None:
    host = WorkItemHost()
    story = host.seed("User Story", "Group", state="New")

    updated = tracker_on(host, "agile").update(story, {"state": "active"})

    assert updated.state == "Active"
    assert field(host, story, "System.State") == "Active"


def test_scrum_defaults_map_active_to_committed() -> None:
    host = WorkItemHost()
    item = host.seed("Product Backlog Item", "Group", state="New")

    tracker_on(host, "scrum").update(item, {"state": "active"})

    assert field(host, item, "System.State") == "Committed"


def test_basic_defaults_map_the_three_states() -> None:
    host = WorkItemHost()
    issue = host.seed("Issue", "Change", state="To Do")
    tracker = tracker_on(host)

    tracker.update(issue, {"state": "active"})
    assert field(host, issue, "System.State") == "Doing"

    tracker.update(issue, {"state": "done"})
    assert field(host, issue, "System.State") == "Done"


def test_a_state_differing_for_one_type_is_overridden() -> None:
    host = WorkItemHost()
    task = host.seed("Task", "Group", state="Doing")
    issue = host.seed("Issue", "Change", state="Doing")
    tracker = tracker_on(
        host, state_map={"done": "Done"}, states_by_type={"Task": {"done": "Closed"}}
    )

    tracker.update(task, {"state": "done"})
    tracker.update(issue, {"state": "done"})

    assert field(host, task, "System.State") == "Closed"
    assert field(host, issue, "System.State") == "Done"


def test_the_configured_states_win_over_the_process_defaults() -> None:
    host = WorkItemHost()
    issue = host.seed("Issue", "Change", state="To Do")
    tracker_on(host, state_map={"active": "In Progress"}).update(issue, {"state": "active"})

    assert field(host, issue, "System.State") == "In Progress"
