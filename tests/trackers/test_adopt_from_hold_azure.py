"""Adopting a hold's hand-made items over the Azure DevOps tracker at the HTTP boundary: the
marker is a tag and a description comment, and a type no level uses is a conflict."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.external_file import Hold, write_holds
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.config import AzureDevOpsTracker
from tests.trackers.ado_work_item_host import WorkItemHost
from tests.trackers.board_support import CHANGE, TYPES, board_section, covering
from tests.trackers.reconciler_support import World

pytestmark = pytest.mark.usefixtures("rest_env")

DESCRIPTION = "<div>Sam wrote this &amp; that</div>"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def azure_world(tmp_path: Path) -> tuple[World, WorkItemHost]:
    host = WorkItemHost()
    section = board_section(["change", "group"])
    assert isinstance(section, AzureDevOpsTracker)
    return World(tmp_path, section, AzureDevOpsWorkItems(section, http=host)), host


def hold_with(world: World, **items: str) -> None:
    write_holds(
        world.change_dir,
        [
            Hold(
                scope=(1,),
                holder="Sam Example",
                link="https://boards.example/items/42",
                since=datetime(2026, 1, 1, tzinfo=UTC),
                items=items,
            )
        ],
    )


def test_adopting_tags_the_item_and_appends_the_comment_without_escaping_it(
    tmp_path: Path,
) -> None:
    world, host = azure_world(tmp_path)
    change = host.seed(TYPES["change"], "Remember lanes")
    group = host.seed(TYPES["group"], "Sam's wording", parent=change, tags="sam-tag")
    host.edit(group, **{"System.Description": DESCRIPTION})
    hold_with(world, change=change, group=group)

    report = world.run([covering(f"{CHANGE}/1", (1,))])

    marker = f"{world.section.marker_prefix}:{CHANGE}:1"
    fields = host.items[int(group)]["fields"]
    sent = [
        op
        for seen in host.calls("PATCH")
        if seen.route.endswith(f"workitems/{group}")
        for op in seen.body
        if op["path"] == "/fields/System.Description"
    ]
    assert sent, "the description was written once, with the comment"
    assert fields["System.Description"] == f"{DESCRIPTION}\n<!-- {marker} -->"
    assert "&lt;!--" not in fields["System.Description"]
    assert [tag.strip() for tag in fields["System.Tags"].split(";")] == ["sam-tag", marker]
    assert fields["System.Title"] == "Sam's wording"
    found = world.tracker.find_by_marker(f"{CHANGE}:1")
    assert found is not None and found.id == group
    assert report.conflicts == ()


def test_an_id_of_a_type_no_level_uses_is_a_conflict_and_no_group_item_is_made(
    tmp_path: Path,
) -> None:
    world, host = azure_world(tmp_path)
    change = host.seed(TYPES["change"], "Remember lanes")
    bug = host.seed("Bug", "A bug somebody filed", parent=change)
    hold_with(world, change=change, group=bug)

    report = world.run([covering(f"{CHANGE}/1", (1,))])

    assert any(bug in conflict and f"{CHANGE}:1" in conflict for conflict in report.conflicts)
    tag = f"{world.section.marker_prefix}:{CHANGE}:1"
    assert not [made for made in host.creates if made.fields.get("System.Tags") == tag]
    mapping = read_tracker(world.change_dir)
    assert mapping is not None and f"{CHANGE}:1" not in mapping.groups


def test_a_hold_naming_the_manual_epic_as_the_change_is_a_conflict_and_the_epic_is_not_written(
    tmp_path: Path,
) -> None:
    host = WorkItemHost()
    section = board_section(["change", "group"], epic=True)
    assert isinstance(section, AzureDevOpsTracker)
    world = World(tmp_path, section, AzureDevOpsWorkItems(section, http=host))
    epic = host.seed(TYPES["epic"], "Manual epic")
    hold_with(world, change=epic)

    report = world.run([covering(f"{CHANGE}/1", (1,))])

    assert any(epic in conflict and "epic" in conflict for conflict in report.conflicts)
    assert not [seen for seen in host.calls("PATCH") if seen.route.endswith(f"workitems/{epic}")]
    mapping = read_tracker(world.change_dir)
    assert mapping is None or mapping.change is None
