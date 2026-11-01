"""Attaching a pull request through the Azure DevOps tracker at the HTTP boundary: one artifact
link on each target item, none on a repeat, and none for a pull request hosted elsewhere
(spec: tracker-push)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.config import AzureDevOpsTracker
from agent_build_kit.trackers.pr_attach import ATTACHED_NAME, attach_pull_request
from tests.factories import stored_unit
from tests.trackers.ado_work_item_host import PROJECT_ID, REPOSITORY_ID, WorkItemHost
from tests.trackers.board_support import CHANGE, board_section
from tests.trackers.reconciler_support import World

pytestmark = pytest.mark.usefixtures("rest_env")

PR_URL = "https://dev.azure.com/example/Some%20Project/_git/app/pullrequest/7"
ARTIFACT = f"vstfs:///Git/PullRequestId/{PROJECT_ID}%2F{REPOSITORY_ID}%2F7"
ELSEWHERE = "https://github.com/example/app/pull/5"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def board(tmp_path: Path) -> tuple[World, WorkItemHost]:
    host = WorkItemHost()
    section = board_section(["change", "group"])
    assert isinstance(section, AzureDevOpsTracker)
    world = World(tmp_path, section, AzureDevOpsWorkItems(section, http=host))
    world.run()
    return world, host


def attach(
    world: World, pr_url: str, errors: list[str] | None = None, uid: str = f"{CHANGE}/1"
) -> tuple[str, ...]:
    unit = stored_unit(uid, change=CHANGE, groups=(1, 2), repo="app")
    return attach_pull_request(
        unit,
        changes_dir=world.changes_dir,
        state_dir=world.state_dir,
        pr_url=pr_url,
        on_error=(lambda key, error: errors.append(key)) if errors is not None else None,
    )


def test_each_target_item_gets_one_artifact_link_and_a_repeat_sends_nothing(
    tmp_path: Path,
) -> None:
    world, host = board(tmp_path)
    patches = len(host.calls("PATCH"))

    first = attach(world, PR_URL)
    second = attach(world, PR_URL)

    assert sorted(first) == [f"{CHANGE}:1", f"{CHANGE}:2"]
    assert second == ()
    assert len(host.calls("PATCH")) == patches + 2
    for marker in (f"{CHANGE}:1", f"{CHANGE}:2"):
        relations = host.items[int(world.item_id(marker))]["relations"]
        assert [r["url"] for r in relations if r["rel"] == "ArtifactLink"] == [ARTIFACT]
    change_relations = host.items[int(world.item_id(CHANGE))]["relations"]
    assert not [r for r in change_relations if r["rel"] == "ArtifactLink"]


def test_the_repository_is_read_in_the_project_the_address_names_not_the_boards(
    tmp_path: Path,
) -> None:
    world, host = board(tmp_path)
    attach(world, PR_URL)

    reads = [s for s in host.seen if s.route == "git/repositories/app"]
    assert len(reads) == 2, "one read for each target item"
    assert all("/Some%20Project/_apis/" in str(s.request.url) for s in reads)
    # The board's own project is another one.
    assert "Example%20Project" not in str(reads[0].request.url)


def test_a_pull_request_hosted_elsewhere_is_not_a_failure_and_is_not_retried(
    tmp_path: Path,
) -> None:
    world, host = board(tmp_path)
    patches = len(host.calls("PATCH"))
    errors: list[str] = []

    first = attach(world, ELSEWHERE, errors)
    second = attach(world, ELSEWHERE, errors)

    assert (first, second, errors) == ((), (), [])
    assert len(host.calls("PATCH")) == patches
    assert not [s for s in host.seen if s.route.startswith("git/")]
    recorded = json.loads((world.state_dir / ATTACHED_NAME).read_text())
    assert recorded == {ELSEWHERE: [f"{CHANGE}:1", f"{CHANGE}:2"]}


def test_units_with_no_pull_request_address_are_recorded_apart(tmp_path: Path) -> None:
    world, host = board(tmp_path)
    errors: list[str] = []

    attach(world, "", errors, uid=f"{CHANGE}/1")
    attach(world, "", errors, uid=f"{CHANGE}/2")

    assert errors == []
    recorded = json.loads((world.state_dir / ATTACHED_NAME).read_text())
    assert sorted(recorded) == [f"{CHANGE}/1", f"{CHANGE}/2"]
