"""The reconciler over the Azure DevOps tracker at the HTTP boundary: the board's own state words
and tags, not the stand-in's."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.config import AzureDevOpsTracker
from tests.trackers.ado_work_item_host import WorkItemHost
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import World

pytestmark = pytest.mark.usefixtures("rest_env")


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def azure_world(tmp_path: Path) -> tuple[World, WorkItemHost]:
    host = WorkItemHost()
    section = board_section(["change", "group"])
    assert isinstance(section, AzureDevOpsTracker)
    return World(tmp_path, section, AzureDevOpsWorkItems(section, http=host)), host


def stored(host: WorkItemHost, item_id: str) -> dict[str, object]:
    return host.items[int(item_id)]["fields"]


def test_a_first_run_of_a_planned_change_sends_no_patch(tmp_path: Path) -> None:
    world, host = azure_world(tmp_path)

    report = world.run()

    assert len(host.creates) == 3
    assert host.calls("PATCH") == []
    assert (report.created, report.updated, report.errors) == (3, 0, 0)


def test_a_second_run_and_a_run_after_losing_the_tracker_file_send_no_patch(
    tmp_path: Path,
) -> None:
    world, host = azure_world(tmp_path)
    world.run()
    (world.change_dir / "tracker.yaml").unlink()
    world.snapshot.unlink()

    report = world.run()

    assert len(host.creates) == 3, "every item is found by its marker"
    assert host.calls("PATCH") == []
    assert (report.created, report.updated, report.errors) == (0, 0, 0)


def test_a_group_moving_to_review_gets_the_tag_and_state_and_keeps_its_marker(
    tmp_path: Path,
) -> None:
    world, host = azure_world(tmp_path)
    world.run([covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)])

    report = world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])

    group = world.item_id(f"{CHANGE}:1")
    tags = [tag.strip() for tag in str(stored(host, group)["System.Tags"]).split(";")]
    assert "in-review" in tags
    assert f"{world.section.marker_prefix}:{CHANGE}:1" in tags
    assert stored(host, group)["System.State"] == "Doing"
    assert report.errors == 0
    assert world.item_id(f"{CHANGE}:1") == group, "the marker still finds the item"


def test_the_tag_is_written_once_and_a_blocked_group_swaps_it(tmp_path: Path) -> None:
    world, host = azure_world(tmp_path)
    world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])
    patches = len(host.calls("PATCH"))

    world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])
    assert len(host.calls("PATCH")) == patches

    world.run([covering(f"{CHANGE}/1", (1,), UnitState.FAILED)])

    tags = str(stored(host, world.item_id(f"{CHANGE}:1"))["System.Tags"])
    assert "blocked" in tags
    assert "in-review" not in tags
