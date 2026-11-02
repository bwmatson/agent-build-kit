"""Someone else's branch or pull request, found by name or by item, keeps a unit from starting."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.units import MERGED, Unit, branch_name
from agent_build_kit.trackers.start_decision import StartDecision, start_decision, start_gate
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge, lookup
from tests.split_start_support import fresh, gate_round, round_ids, store_of
from tests.trackers.board_support import CHANGE
from tests.trackers.start_support import FIRST, SECOND, board, board_in, item

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


class Forged(StandInForge):
    """The stand-in that answers a pull request on one branch only, and counts its listings."""

    def __init__(self, *, on: str = "", number: int = 7, **kwargs) -> None:  # noqa: ANN003
        super().__init__(number=number, **kwargs)
        self.on = on
        self.found: list[str] = []
        self.listings = 0

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        self.found.append(head)
        return self.number if head == self.on else None

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        self.listings += 1
        return super().list_prs(repo, head_prefix=head_prefix)


class Lookups:
    """The forge lookups a decision made, answering with the stand-in."""

    def __init__(self, forge: StandInForge) -> None:
        self.forge = forge
        self.repos: list[str] = []

    def __call__(self, repo: str) -> tuple[StandInForge, RepoId]:
        self.repos.append(repo)
        return lookup(self.forge)(repo)


def pull(
    item_id: str, *, state: str = "open", at: str = "body", head: str = OTHER_BRANCH, text: str = ""
) -> PullRequest:
    text = text or f"Takes AB#{item_id} on my own."
    return PullRequest(
        number=31,
        head=head,
        base="main",
        state=state,
        title=text if at == "title" else "A change",
        body=text if at == "body" else "",
    )


def first() -> Unit:
    return stored_unit(FIRST, change=CHANGE, groups=(1,))


def decide(unit: Unit, changes_dir: Path, forge: StandInForge, remote: Asked) -> StartDecision:
    return start_decision(
        unit, changes_dir=changes_dir, for_repo=Lookups(forge), remote_head_of=remote
    )


def test_a_remote_branch_of_the_units_name_with_no_local_unit_blocks_the_start(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    unit = first()
    remote = Asked("abc123")

    decision = decide(unit, inst.changes_dir, StandInForge(), remote)

    assert decision.outcome == "skip"
    assert f"foreign branch {branch_name(unit)}" in decision.reason
    assert remote.branches == [branch_name(unit)]
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_pull_request_of_the_units_branch_name_blocks_the_start_naming_it(
    tmp_path: Path,
) -> None:
    _, inst = board_in(tmp_path)
    unit = first()
    forge = Forged(on=branch_name(unit))

    decision = decide(unit, inst.changes_dir, forge, Asked())

    assert decision.outcome == "skip"
    assert "foreign pull request 7" in decision.reason
    assert forge.found == [branch_name(unit)]


@pytest.mark.parametrize("at", ["body", "title"])
def test_a_pull_request_on_another_branch_naming_a_covered_item_blocks_the_start(
    tmp_path: Path, at: str
) -> None:
    world, inst = board_in(tmp_path)
    forge = StandInForge(prs=[pull(item(world, "1"), at=at)])

    decision = decide(first(), inst.changes_dir, forge, Asked())

    assert decision.outcome == "skip"
    assert "foreign pull request 31" in decision.reason
    assert item(world, "1") in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_pull_request_naming_an_item_the_unit_does_not_cover_does_not_block(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    forge = StandInForge(prs=[pull(item(world, "2"))])
    remote = Asked()

    decision = decide(first(), inst.changes_dir, forge, remote)

    assert remote.branches == [branch_name(first())]
    assert decision.outcome == "start"


def test_a_pull_request_naming_an_id_that_only_begins_with_a_covered_id_does_not_block(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    longer = f"{item(world, '1')}3"
    forge = StandInForge(prs=[pull(longer)])
    remote = Asked()

    decision = decide(first(), inst.changes_dir, forge, remote)

    assert remote.branches == [branch_name(first())]
    assert decision.outcome == "start"


@pytest.mark.parametrize("state", ["closed", MERGED])
def test_a_pull_request_that_is_not_open_does_not_block(tmp_path: Path, state: str) -> None:
    world, inst = board_in(tmp_path)
    forge = StandInForge(prs=[pull(item(world, "1"), state=state)])
    remote = Asked()

    decision = decide(first(), inst.changes_dir, forge, remote)

    assert remote.branches == [branch_name(first())]
    assert decision.outcome == "start"


def test_a_failed_read_of_the_remote_is_a_wait_that_claims_nothing(tmp_path: Path) -> None:
    world, inst = board_in(tmp_path)
    remote = Asked(None)

    decision = decide(first(), inst.changes_dir, StandInForge(), remote)

    assert decision.outcome == "wait"
    assert branch_name(first()) in decision.reason
    assert world.tracker.get(item(world, "1")).assignees == ()


def test_a_pull_request_of_a_sibling_unit_is_the_kits_own_on_a_change_only_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, _ = board(tmp_path, ["change"])
    change_item = world.item_id(CHANGE)
    sibling = stored_unit(FIRST, change=CHANGE, groups=(1,))
    unit = stored_unit(SECOND, change=CHANGE, groups=(2,))
    graph = [sibling, unit]

    def gate(prs: list[PullRequest]) -> StartDecision:
        monkeypatch.setattr(forges, "for_repo", lookup(StandInForge(prs=prs)))
        return start_gate(unit, graph, changes_dir=world.changes_dir)

    assert gate([pull(change_item, head=branch_name(sibling))]).outcome == "start"
    assert gate([pull(change_item)]).outcome == "skip"


def test_a_unit_with_a_branch_or_pull_request_of_its_own_triggers_no_lookup(
    tmp_path: Path,
) -> None:
    world, inst = board_in(tmp_path)
    forge = StandInForge(prs=[pull(item(world, "2"))])
    asked = Lookups(forge)
    remote = Asked("")

    start_decision(first(), changes_dir=inst.changes_dir, for_repo=asked, remote_head_of=remote)
    assert asked.repos != []
    for own in ({"branch": "spec/lane-dedupe/1"}, {"pr": 12}):
        asked.repos.clear()
        remote.branches.clear()
        mine = stored_unit(FIRST, change=CHANGE, groups=(1,), **own)

        decision = start_decision(
            mine, changes_dir=inst.changes_dir, for_repo=asked, remote_head_of=remote
        )

        assert decision.outcome == "start"
        assert asked.repos == []
        assert remote.branches == []


def test_a_round_lists_the_pull_requests_of_a_repo_once_for_all_its_planned_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_round(monkeypatch)
    _, inst = board_in(tmp_path)
    forge = Forged()
    monkeypatch.setattr(forges, "for_repo", lookup(forge))
    store = store_of(inst)
    fresh(store, FIRST)
    fresh(store, SECOND)

    assert sorted(round_ids(inst, store)) == [FIRST, SECOND]

    assert forge.listings == 1
