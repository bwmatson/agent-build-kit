"""A merged pull request on items a person holds closes the work they built by hand (spec:
unit-claim), through the hold and hand-merge recording of `external-hand-off`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges, trackers
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import DONE, Hold, read_holds
from agent_build_kit.pipeline.task_progress import TASKS_FILE, progress_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED
from tests.forges.stand_in import StandInForge, lookup
from tests.split_start_support import fresh, gate_round, round_ids, store_of
from tests.trackers.board_support import CHANGE
from tests.trackers.start_support import FIRST, PERSON, SECOND, board_in, taken_by_person

pytestmark = pytest.mark.usefixtures("scripted_engine")

PULL = 31
COMMIT = "d" * 40
HAND_BRANCH = "alice/by-hand"


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def pull(*item_ids: str, state: str = MERGED) -> PullRequest:
    """The person's pull request on a branch of their own choosing, carrying the items."""
    return PullRequest(
        number=PULL,
        head=HAND_BRANCH,
        base="main",
        state=state,
        title="By hand",
        body="\n".join(f"Done AB#{item_id}" for item_id in item_ids),
    )


class Hosted:
    """The forge the round and the hand-merge recording both reach, and the repos asked of it."""

    def __init__(self, forge: StandInForge) -> None:
        self.forge = forge
        self.asked: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch, inst: Installation) -> None:
        resolve = lookup(self.forge)

        def for_repo(repo: str):  # noqa: ANN202
            self.asked.append(repo)
            return resolve(repo)

        monkeypatch.setattr(forges, "for_repo", for_repo)
        monkeypatch.setattr(inst, "forge_of", for_repo)


def forge_with(*prs: PullRequest, merged: bool = True) -> StandInForge:
    forge = StandInForge(prs=prs)
    if merged:
        forge.merged[PULL] = COMMIT
    return forge


def holds_of(inst: Installation) -> tuple[Hold, ...]:
    return read_holds(inst.changes_dir / CHANGE)


def checked(inst: Installation) -> list[str]:
    """The numbers of the tasks ticked in the change's tracking copy of `tasks.md`."""
    copy = progress_dir(inst, CHANGE) / TASKS_FILE
    lines = copy.read_text().splitlines() if copy.exists() else []
    return [line.split()[2] for line in lines if line.startswith("- [x]")]


def planned(inst: Installation, *ids: str) -> UnitStore:
    store = store_of(inst)
    for uid in ids:
        fresh(store, uid)
    return store


def test_a_merged_pull_request_on_held_items_records_the_hold_and_the_hand_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    held = taken_by_person(world, "1")
    Hosted(forge_with(pull(held))).install(monkeypatch, inst)
    store = planned(inst, FIRST)
    fresh(store, SECOND, depends_on=(FIRST,))

    round_ids(inst, store)

    (hold,) = holds_of(inst)
    assert hold.holder == PERSON
    assert hold.scope == (1,)
    assert hold.link.endswith(f"/pull/{PULL}")
    assert hold.status == DONE
    unit = store.get(FIRST)
    assert unit.state == MERGED
    assert unit.merge_sha == COMMIT
    assert {"1.1", "1.2"} <= set(checked(inst))
    assert round_ids(inst, store) == [SECOND]


def test_a_second_round_records_nothing_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    held = taken_by_person(world, "1")
    Hosted(forge_with(pull(held))).install(monkeypatch, inst)
    store = planned(inst, FIRST, SECOND)
    round_ids(inst, store)
    holds, history = holds_of(inst), store.get(FIRST).history

    round_ids(inst, store)

    assert holds_of(inst) == holds
    assert store.get(FIRST).history == history
    assert len(holds) == 1


def test_a_pull_request_closed_without_merging_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    held = taken_by_person(world, "1")
    Hosted(forge_with(pull(held, state="closed"), merged=False)).install(monkeypatch, inst)
    store = planned(inst, FIRST, SECOND)

    assert round_ids(inst, store) == [SECOND]

    assert holds_of(inst) == ()
    assert store.get(FIRST).state == PLANNED


def test_a_merged_pull_request_naming_one_of_two_groups_records_that_group_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    first, second = taken_by_person(world, "1"), taken_by_person(world, "2")
    Hosted(forge_with(pull(first))).install(monkeypatch, inst)
    store = store_of(inst)
    fresh(store, "lane-dedupe/3", groups=(1, 2))

    round_ids(inst, store)

    done = [hold for hold in holds_of(inst) if hold.status == DONE]
    assert [hold.scope for hold in done] == [(1,)]
    assert store.get("lane-dedupe/3").state == PLANNED
    assert world.tracker.get(second).assignees != ()


def test_a_merged_pull_request_naming_an_item_the_person_does_not_hold_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    taken_by_person(world, "1")
    free = world.item_id(f"{CHANGE}:2")
    Hosted(forge_with(pull(free))).install(monkeypatch, inst)
    store = planned(inst, FIRST)

    round_ids(inst, store)

    assert holds_of(inst) == ()
    assert store.get(FIRST).state == PLANNED


def test_a_repo_with_no_tracker_makes_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, inst = board_in(tmp_path)
    held = taken_by_person(world, "1")
    host = Hosted(forge_with(pull(held)))
    host.install(monkeypatch, inst)
    store = planned(inst, FIRST)
    fresh(store, "elsewhere/1", repo="platform")

    round_ids(inst, store)

    assert store.get(FIRST).state == MERGED
    assert "platform" not in host.asked
