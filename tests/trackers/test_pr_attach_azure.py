"""Attaching a pull request through the Azure DevOps tracker at the HTTP boundary: one artifact
link on each target item, and none on a repeat (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.config import AzureDevOpsTracker
from agent_build_kit.trackers.pr_attach import attach_pull_request
from tests.factories import stored_unit
from tests.trackers.ado_work_item_host import PROJECT_ID, WorkItemHost
from tests.trackers.board_support import CHANGE, board_section
from tests.trackers.reconciler_support import World

pytestmark = pytest.mark.usefixtures("rest_env")

PR_URL = "https://dev.azure.com/example/Some%20Project/_git/app/pullrequest/7"
ARTIFACT = f"vstfs:///Git/PullRequestId/{PROJECT_ID}%2Frepo-app%2F7"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def test_each_target_item_gets_one_artifact_link_and_a_repeat_sends_nothing(
    tmp_path: Path,
) -> None:
    host = WorkItemHost()
    section = board_section(["change", "group"])
    assert isinstance(section, AzureDevOpsTracker)
    world = World(tmp_path, section, AzureDevOpsWorkItems(section, http=host))
    world.run()
    unit = stored_unit(f"{CHANGE}/1", change=CHANGE, groups=(1, 2), repo="app")
    patches = len(host.calls("PATCH"))

    first = attach_pull_request(
        unit, changes_dir=world.changes_dir, state_dir=world.state_dir, pr_url=PR_URL
    )
    second = attach_pull_request(
        unit, changes_dir=world.changes_dir, state_dir=world.state_dir, pr_url=PR_URL
    )

    assert sorted(first) == [f"{CHANGE}:1", f"{CHANGE}:2"]
    assert second == ()
    assert len(host.calls("PATCH")) == patches + 2
    for marker in (f"{CHANGE}:1", f"{CHANGE}:2"):
        relations = host.items[int(world.item_id(marker))]["relations"]
        assert [r["url"] for r in relations if r["rel"] == "ArtifactLink"] == [ARTIFACT]
    change_relations = host.items[int(world.item_id(CHANGE))]["relations"]
    assert not [r for r in change_relations if r["rel"] == "ArtifactLink"]
