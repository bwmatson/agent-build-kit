"""Someone else's branch or pull request, found by name or by item, keeps a unit from starting."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.units import Unit, branch_name
from agent_build_kit.trackers.start_decision import StartDecision, start_decision
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge, lookup
from tests.trackers.start_support import board_in, item

pytestmark = pytest.mark.usefixtures("scripted_engine")

OTHER_BRANCH = "alice/my-own-branch"


class Asked:
    """The remote reads a decision made, answering with `head`."""

    def __init__(self, head: str | None = "") -> None:
        self.head = head
        self.branches: list[str] = []

    def __call__(self, repo: Path, branch: str) -> str | None:
        self.branches.append(branch)
        return self.head


class Lookups:
    """The forge lookups a decision made, answering with the stand-in."""

    def __init__(self, forge: StandInForge) -> None:
        self.forge = forge
        self.repos: list[str] = []

    def __call__(self, repo: str) -> tuple[StandInForge, RepoId]:
        self.repos.append(repo)
        return lookup(self.forge)(repo)


def pull(item_id: str, *, state: str = "open", at: str = "body") -> PullRequest:
    text = f"Takes AB#{item_id} on my own."
    return PullRequest(
        number=31,
        head=OTHER_BRANCH,
        base="main",
        state=state,
        title=text if at == "title" else "A change",
        body=text if at == "body" else "",
    )


def decide(unit: Unit, changes_dir: Path, forge: StandInForge, remote: Asked) -> StartDecision:
    return start_decision(
        unit, changes_dir=changes_dir, for_repo=Lookups(forge), remote_head_of=remote
    )


def test_a_remote_branch_of_the_units_name_with_no_local_unit_blocks_the_start(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))
    remote = Asked("abc123")

    decision = decide(unit, inst.changes_dir, StandInForge(), remote)

    assert decision.outcome != "start"
    assert branch_name(unit) in decision.reason
    assert "branch" in decision.reason
    assert remote.branches == [branch_name(unit)]
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_pull_request_of_the_units_branch_name_blocks_the_start_naming_it(
    tmp_path: Path,
) -> None:
    _, inst = board_in(tmp_path)
    unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))

    decision = decide(unit, inst.changes_dir, StandInForge(existing=7), Asked())

    assert decision.outcome != "start"
    assert "pull request" in decision.reason
    assert "7" in decision.reason


@pytest.mark.parametrize("at", ["body", "title"])
def test_a_pull_request_on_another_branch_naming_a_covered_item_blocks_the_start(
    tmp_path: Path, at: str
) -> None:
    world, inst = board_in(tmp_path)
    unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))
    forge = StandInForge(prs=[pull(item(world, "1"), at=at)])

    decision = decide(unit, inst.changes_dir, forge, Asked())

    assert decision.outcome != "start"
    assert "31" in decision.reason
    assert item(world, "1") in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_pull_request_naming_an_item_the_unit_does_not_cover_does_not_block(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))
    forge = StandInForge(prs=[pull(item(world, "2"))])
    remote = Asked()

    decision = decide(unit, inst.changes_dir, forge, remote)

    assert remote.branches == [branch_name(unit)]
    assert decision.outcome == "start"


def test_a_closed_unmerged_pull_request_does_not_block(tmp_path: Path) -> None:
    world, inst = board_in(tmp_path)
    unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))
    forge = StandInForge(prs=[pull(item(world, "1"), state="closed")])
    remote = Asked()

    decision = decide(unit, inst.changes_dir, forge, remote)

    assert remote.branches == [branch_name(unit)]
    assert decision.outcome == "start"


@pytest.mark.parametrize("own", [{"branch": "spec/lane-dedupe/1"}, {"pr": 12}])
def test_a_unit_with_a_branch_or_pull_request_of_its_own_triggers_no_lookup(
    tmp_path: Path, own: dict[str, object]
) -> None:
    world, inst = board_in(tmp_path)
    mine = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,), **own)
    fresh_unit = stored_unit("lane-dedupe/1", change="lane-dedupe", groups=(1,))
    asked = Lookups(StandInForge(prs=[pull(item(world, "2"))]))
    remote = Asked()

    start_decision(fresh_unit, changes_dir=inst.changes_dir, for_repo=asked, remote_head_of=remote)
    assert asked.repos != []
    asked.repos.clear()
    remote.branches.clear()
    decision = start_decision(
        mine, changes_dir=inst.changes_dir, for_repo=asked, remote_head_of=remote
    )

    assert decision.outcome == "start"
    assert asked.repos == []
    assert remote.branches == []
