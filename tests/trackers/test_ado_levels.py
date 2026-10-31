"""Nested levels, the manual epic and pull request links on Azure DevOps work items: a child
is parented by the level above it, the epic is only read, and a pull request is attached
as an artifact link once."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from tests.forges.azure_rest_host import PROJECT_ID
from tests.trackers.ado_support import section
from tests.trackers.ado_work_item_host import FORWARD, REVERSE, WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

ARTIFACT = "ArtifactLink"
PROJECT = PROJECT_ID
REPOSITORY = "66666666-7777-8888-9999-000000000000"


def tracker_on(host: WorkItemHost, process: str = "basic") -> AzureDevOpsWorkItems:
    return AzureDevOpsWorkItems(section(process), http=host)


def parent_of(host: WorkItemHost, item_id: str) -> str | None:
    relations = host.items[int(item_id)]["relations"]
    return next((r["url"].rsplit("/", 1)[-1] for r in relations if r["rel"] == REVERSE), None)


def addressed_to(host: WorkItemHost, item_id: str) -> list[str]:
    """The methods of the requests whose route is one item's."""
    return [s.method for s in host.seen if s.route == f"wit/workitems/{item_id}"]


def artifacts(host: WorkItemHost, item_id: str) -> list[str]:
    return [r["url"] for r in host.items[int(item_id)]["relations"] if r["rel"] == ARTIFACT]


def attach(tracker: AzureDevOpsWorkItems, item_id: str, pull_request_id: int = 7) -> bool:
    return tracker.link_pull_request(
        item_id, project_id=PROJECT, repository_id=REPOSITORY, pull_request_id=pull_request_id
    )


def test_a_task_is_created_under_a_group_item_when_task_is_a_level() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host, "scrum")
    change = host.seed("Feature", "Change")
    group = host.seed("Product Backlog Item", "Group", parent=change)

    task = tracker.create("task", "Task", parent=group, markers=("add-marker:g1.t1",))

    assert host.creates[-1].type == "Task"
    assert (task.kind, task.parent_id) == ("task", group)
    assert parent_of(host, task.id) == group
    # The parent is read, to check it is of the level above.
    assert "GET" in addressed_to(host, group)


def test_a_task_is_created_under_the_change_item_when_group_is_not_a_level() -> None:
    host = WorkItemHost()
    skipping = section("scrum").model_copy(
        update={
            "levels": ("change", "task"),
            "types": {"epic": "Epic", "change": "Feature", "task": "Task"},
        }
    )
    change = host.seed("Feature", "Change")

    task = AzureDevOpsWorkItems(skipping, http=host).create("task", "Task", parent=change)

    assert (task.kind, task.parent_id) == ("task", change)
    assert [r["rel"] for r in host.creates[-1].relations] == [REVERSE]
    assert "GET" in addressed_to(host, change)


def test_a_task_is_refused_under_a_change_item_when_group_is_a_level() -> None:
    host = WorkItemHost()
    change = host.seed("Feature", "Change")

    with pytest.raises(ValueError, match="group"):
        tracker_on(host, "scrum").create("task", "Task", parent=change)

    assert host.creates == []


def test_a_first_level_item_is_created_under_a_manual_epic_that_is_only_read() -> None:
    host = WorkItemHost()
    epic = host.seed("Epic", "Roadmap")
    tracker = tracker_on(host)

    change = tracker.create("change", "Change", parent=epic, markers=("add-marker",))

    assert [r["rel"] for r in host.creates[0].relations] == [REVERSE]
    assert parent_of(host, change.id) == epic
    assert change.parent_id == epic
    # The epic was read, to check its type, and nothing else was sent to it.
    assert addressed_to(host, epic) == ["GET"]
    assert host.items[int(epic)]["rev"] == 1
    assert FORWARD in [r["rel"] for r in host.items[int(epic)]["relations"]]


def test_a_first_level_item_with_no_epic_is_created_at_the_top() -> None:
    host = WorkItemHost()
    epic = host.seed("Epic", "Roadmap")
    tracker = tracker_on(host)
    tracker.create("change", "Under the epic", parent=epic)

    top = tracker.create("change", "At the top")

    assert host.creates[-1].relations == []
    assert top.parent_id is None
    assert parent_of(host, top.id) is None
    assert addressed_to(host, epic) == ["GET"]


def test_a_parent_that_is_not_an_epic_is_refused_for_a_first_level_item() -> None:
    host = WorkItemHost()
    issue = host.seed("Issue", "Not an epic")

    with pytest.raises(ValueError, match="epic"):
        tracker_on(host).create("change", "Change", parent=issue)

    assert host.creates == []


def test_a_pull_request_is_attached_as_an_artifact_link_to_each_item_given() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    change = host.seed("Issue", "Change")
    first = host.seed("Task", "First", parent=change)
    second = host.seed("Task", "Second", parent=change)
    artifact = f"vstfs:///Git/PullRequestId/{PROJECT}%2F{REPOSITORY}%2F7"

    assert attach(tracker, first) is True
    assert attach(tracker, second) is True

    assert artifacts(host, first) == [artifact]
    assert artifacts(host, second) == [artifact]
    assert artifacts(host, change) == []


def test_a_repeated_pull_request_link_attaches_nothing() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    group = host.seed("Task", "Group", parent=host.seed("Issue", "Change"))
    attach(tracker, group)
    sent = len(host.calls("PATCH"))
    revision = host.items[int(group)]["rev"]

    assert attach(tracker, group) is False

    assert len(host.calls("PATCH")) == sent
    assert len(artifacts(host, group)) == 1
    assert host.items[int(group)]["rev"] == revision


def test_another_pull_request_is_attached_beside_the_first() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    group = host.seed("Task", "Group", parent=host.seed("Issue", "Change"))
    attach(tracker, group, 7)

    assert attach(tracker, group, 8) is True

    assert [url.rsplit("%2F", 1)[-1] for url in artifacts(host, group)] == ["7", "8"]
