"""Conditional updates, assignment and claim on Azure DevOps work items: an update carries a
test of the revision, a claim reports whether it won, states map from the configuration and
the blocked and in-review markers are tags."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems, UnknownWorkItemType
from agent_build_kit.trackers.base import StaleRevision
from tests.trackers.ado_support import section, tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

SYNC = "sync@example.com"
OTHER = "other@example.com"


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


def test_clearing_the_assignee_sends_an_empty_value_and_leaves_the_field_absent() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group")
    tracker = tracker_on(host)
    assert tracker.claim(group) is True

    tracker.set_assignee(group, "")

    patch = host.calls("PATCH", f"wit/workitems/{group}")[-1].body
    assert {"op": "add", "path": "/fields/System.AssignedTo", "value": ""} in patch
    assert "System.AssignedTo" not in host.items[int(group)]["fields"]
    assert tracker.get(group).assignees == ()


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


def test_an_update_returns_the_item_with_its_parent() -> None:
    host = WorkItemHost()
    change = host.seed("Issue", "Change")
    group = host.seed("Task", "Group", parent=change)

    updated = tracker_on(host).update(group, {"title": "Renamed"})

    assert updated.parent_id == change
    assert host.calls("PATCH", f"wit/workitems/{group}")[-1].params["$expand"] == "relations"


def test_a_body_update_keeps_the_item_findable_by_its_marker() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    created = tracker.create("group", "Group", "First", markers=("feature:g1",))

    tracker.update(created.id, {"body": "Second"})

    found = tracker.find_by_marker("feature:g1")
    assert found is not None
    assert (found.id, found.body) == (created.id, "Second")


def test_a_claim_of_an_item_the_sync_identity_holds_is_held_and_sends_no_patch() -> None:
    host = WorkItemHost()
    group = host.seed("Task", "Group", assigned_to=SYNC)

    assert tracker_on(host).claim(group) is True

    assert host.calls("PATCH") == []


def test_a_state_unmapped_for_the_process_is_refused_and_sends_no_patch() -> None:
    host = WorkItemHost()
    issue = host.seed("Issue", "Change", state="To Do")

    with pytest.raises(ValueError, match="active"):
        AzureDevOpsWorkItems(
            section("basic").model_copy(update={"process": "cmmi"}), http=host
        ).update(issue, {"state": "active"})

    assert host.calls("PATCH") == []


def test_an_epic_is_never_written_to() -> None:
    host = WorkItemHost()
    epic = host.seed("Epic", "Roadmap")
    tracker = tracker_on(host)

    with pytest.raises(UnknownWorkItemType):
        tracker.claim(epic)
    with pytest.raises(UnknownWorkItemType):
        tracker.set_assignee(epic, SYNC)
    with pytest.raises(UnknownWorkItemType):
        tracker.set_assignee(epic, SYNC, expected_revision="1")
    with pytest.raises(UnknownWorkItemType):
        tracker.link_pull_request(epic, project_id="p", repository_id="r", pull_request_id=7)
    with pytest.raises(UnknownWorkItemType):
        tracker.set_tag(epic, "blocked", True)
    with pytest.raises(UnknownWorkItemType):
        tracker.update(epic, {"title": "Mine"})

    assert host.calls("PATCH") == []


def test_the_identity_is_read_once_and_asked_for_at_the_preview_version() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)

    tracker.claim(host.seed("Task", "A"))
    tracker.claim(host.seed("Task", "B"))

    asked = host.calls("GET", "connectiondata")
    assert len(asked) == 1
    assert "-preview" in asked[0].params["api-version"]
