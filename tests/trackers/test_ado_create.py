"""Creating and reading Azure DevOps work items: the type follows the configuration, a create
is one request carrying the parent link, and an item is found again by its marker."""

from __future__ import annotations

import re

import httpx
import pytest

from agent_build_kit.forges.transport import HostError
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems, UnknownWorkItemType
from agent_build_kit.trackers.base import Item, ItemKind
from tests.trackers.ado_support import AREA_PATH, ITERATION_PATH, PROCESS_TYPES, section
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

PARENT = "System.LinkTypes.Hierarchy-Reverse"
# The kit's level, by the kind the protocol names it.
KINDS: dict[str, ItemKind] = {"change": "feature", "group": "story", "task": "task"}


def tracker_on(host: WorkItemHost, process: str = "basic") -> AzureDevOpsWorkItems:
    return AzureDevOpsWorkItems(section(process), http=host)


def test_a_group_item_is_created_under_a_change_item_in_one_request() -> None:
    host = WorkItemHost()
    change = host.seed("Issue", "Change")

    item = tracker_on(host).create("story", "Group one", "Do it", change, markers=("feature:g1",))

    assert len(host.creates) == 1
    made = host.creates[0]
    assert made.type == "Task"
    assert made.content_type == "application/json-patch+json"
    assert made.fields["System.Title"] == "Group one"
    assert re.search(r"<!--[^>]*feature:g1[^>]*-->", made.fields["System.Description"])
    assert made.fields["System.AreaPath"] == AREA_PATH
    assert made.fields["System.IterationPath"] == ITERATION_PATH
    assert [(r["rel"], r["url"].rsplit("/", 1)[-1]) for r in made.relations] == [(PARENT, change)]
    assert (item.kind, item.parent_id) == ("story", change)
    assert item.revision
    assert item.url


def test_the_description_is_escaped_text_and_the_body_reads_back_as_written() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)

    made = tracker.create("feature", "Change", "a < b & c", markers=("feature",))

    description = host.creates[0].fields["System.Description"]
    assert "a &lt; b &amp; c" in description
    assert "a < b" not in description
    assert tracker.get(made.id).body == "a < b & c"


CASES = [
    (process, level, types[level])
    for process, types in PROCESS_TYPES.items()
    for level in ("change", "group", "task")
    if level in types
]


@pytest.mark.parametrize(("process", "level", "expected"), CASES)
def test_the_type_of_a_level_follows_the_configuration(
    process: str, level: str, expected: str
) -> None:
    host = WorkItemHost()
    tracker = tracker_on(host, process)
    parent: str | None = None
    for above in ("change", "group", "task"):
        if above not in PROCESS_TYPES[process]:
            continue
        made = tracker.create(KINDS[above], f"{above} item", parent=parent)
        if above == level:
            break
        parent = made.id

    assert host.creates[-1].type == expected


def test_each_level_carries_its_marker_key_and_its_parent() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host, "scrum")

    change = tracker.create("feature", "Change", markers=("add-marker",))
    group = tracker.create("story", "Group", parent=change.id, markers=("add-marker:g1",))
    task = tracker.create("task", "Task", parent=group.id, markers=("add-marker:g1.t1",))

    assert (change.markers, group.markers, task.markers) == (
        ("add-marker",),
        ("add-marker:g1",),
        ("add-marker:g1.t1",),
    )
    assert (task.kind, task.parent_id) == ("task", group.id)
    assert tracker.get(task.id).markers == ("add-marker:g1.t1",)


def test_a_created_item_is_found_by_its_marker() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    made = tracker.create("feature", "Change", markers=("add-marker",))

    found = tracker.find_by_marker("add-marker")

    assert found is not None
    assert found.id == made.id
    assert tracker.find_by_marker("other-change") is None


def test_an_item_whose_create_answer_was_lost_is_found_and_not_created_twice() -> None:
    host = WorkItemHost(lose_create_answer=True)
    tracker = tracker_on(host)

    with pytest.raises(HostError):
        tracker.create("feature", "Change", markers=("add-marker",))
    found = tracker.find_by_marker("add-marker")

    assert isinstance(found, Item)
    assert found.title == "Change"
    assert len(host.creates) == 1


def test_the_children_of_a_change_item_come_from_the_forward_link() -> None:
    host = WorkItemHost()
    change = host.seed("Issue", "Change")
    first = host.seed("Task", "First", parent=change)
    second = host.seed("Task", "Second", parent=change)
    host.seed("Task", "Elsewhere", parent=host.seed("Issue", "Other change"))

    found = tracker_on(host).children(change)

    assert [(item.id, item.kind, item.parent_id) for item in found] == [
        (first, "story", change),
        (second, "story", change),
    ]


def test_a_marker_is_found_exactly_and_not_as_part_of_a_longer_one() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host, "scrum")
    # The longer marker is made first, so a substring match would find it first.
    group = tracker.create("story", "Group", markers=("add-marker:g1",))
    change = tracker.create("feature", "Change", markers=("add-marker",))

    found = tracker.find_by_marker("add-marker")

    assert found is not None
    assert found.id == change.id
    assert found.id != group.id
    assert tracker.find_by_marker("add-mark") is None


def test_the_marker_is_searched_by_a_field_the_query_language_matches_by_substring() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    tracker.create("feature", "Change", markers=("add-marker",))

    tracker.find_by_marker("add-marker")

    (query,) = host.calls("POST", "wit/wiql")
    assert query.body is not None
    assert "[System.Tags] Contains" in query.body["query"]
    assert "System.Description" not in query.body["query"]


def test_the_stand_in_refuses_contains_on_the_description_as_the_service_does() -> None:
    host = WorkItemHost()
    query = "SELECT [System.Id] FROM WorkItems WHERE [System.Description] Contains 'x'"
    url = "https://dev.azure.com/example/Some%20Project/_apis/wit/wiql"

    with httpx.Client(transport=host) as client:
        reply = client.post(url, params={"api-version": "7.1"}, json={"query": query})

    assert reply.status_code == 400


def test_a_child_of_a_type_no_level_uses_is_left_out_of_the_children() -> None:
    host = WorkItemHost()
    change = host.seed("Issue", "Change")
    group = host.seed("Task", "Group", parent=change)
    host.seed("Bug", "A person's bug", parent=change)

    found = tracker_on(host).children(change)

    assert [item.id for item in found] == [group]


def test_an_item_of_a_type_no_level_uses_is_refused_by_name_when_read() -> None:
    host = WorkItemHost()
    bug = host.seed("Bug", "A person's bug")

    with pytest.raises(UnknownWorkItemType, match=rf"{bug}.*'Bug'"):
        tracker_on(host).get(bug)


def test_a_multi_line_body_keeps_its_line_breaks_on_the_board_and_reads_back_exact() -> None:
    host = WorkItemHost()
    tracker = tracker_on(host)
    body = "first\nsecond <b>\n\n- third"

    made = tracker.create("feature", "Change", body, markers=("add-marker",))

    description = host.creates[0].fields["System.Description"]
    assert "first<br>second &lt;b&gt;<br><br>- third" in description
    assert tracker.get(made.id).body == body


def test_a_group_type_left_to_story_type_is_the_type_of_the_group_level() -> None:
    host = WorkItemHost()
    plain = section("basic").model_copy(update={"types": {"change": "Issue"}})

    AzureDevOpsWorkItems(plain, http=host).create("story", "Group")

    assert host.creates[0].type == plain.story_type


def test_a_level_not_in_use_cannot_be_created() -> None:
    host = WorkItemHost()

    with pytest.raises(ValueError, match="no work item type"):
        tracker_on(host, "basic").create("task", "Task")
