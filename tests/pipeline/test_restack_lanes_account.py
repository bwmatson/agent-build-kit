"""The lanes of a workspace count their running restacks per account too (spec:
account-project-limits): an account's cap holds across its projects' lanes, a restack of a full
account waits and starts when another of the account ends, whichever lane it is in, and the lanes
say whether a project's lane or its account is at its cap.

Nothing waits on the clock: a restack ends when the test releases it, and a wait is on the
events the fake restacks set or on a future the lanes complete.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.restack_lane_fakes import WAIT, Restacks
from tests.restack_lanes_fakes import API, DOCS, WEB, Made, unit_of

# `app` runs on the account `kit`; `platform` on the default account, which has no label.
ACCOUNTS: dict[str, str | None] = {"app": "kit", "platform": None}


def account_of(unit: StoredUnit) -> Hashable:
    return ACCOUNTS[unit.repo]


class Caps:
    """The restack cap each account sets; an account not named sets none."""

    def __init__(self, **caps: int) -> None:
        self.by_account: dict[str, int] = dict(caps)

    def __call__(self, account: Hashable) -> int | None:
        return self.by_account.get(account if isinstance(account, str) else "")


@pytest.fixture
def restacks() -> Restacks:
    return Restacks()


@pytest.fixture
def made(tmp_path: Path, restacks: Restacks) -> Made:
    return Made(tmp_path / "locks", restacks)


def lanes_of(
    made: Made,
    restacks: Restacks,
    caps: Callable[[Hashable], int | None],
    of: Callable[[StoredUnit], Hashable] = account_of,
) -> Iterator[RestackLanes]:
    with RestackLanes(made, owed=lambda units: made.owed, account_of=of, account_cap=caps) as lanes:
        yield lanes
        restacks.release_all()
        lanes.drain()


@pytest.fixture
def one_at_a_time(made: Made, restacks: Restacks) -> Iterator[RestackLanes]:
    """Lanes of cap two each, the account `kit` allowing one restack at once."""
    yield from lanes_of(made, restacks, Caps(kit=1))


def drained_within_the_wait(lanes: RestackLanes) -> bool:
    """Whether `drain` returns: a lost wakeup or a deadlock would leave it waiting."""
    drained = threading.Thread(target=lanes.drain, daemon=True)
    drained.start()
    drained.join(timeout=WAIT)
    return not drained.is_alive()


def test_two_projects_of_a_one_restack_account_run_one_and_the_other_waits(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    assert restacks.begun["feature/1"].wait(WAIT)

    one_at_a_time.hand_over(unit_of(2, API))

    assert one_at_a_time.running == ["feature/1"]
    assert one_at_a_time.waiting == ["feature/2"]
    assert "feature/2" not in restacks.started


def test_the_waiting_restack_of_the_other_lane_starts_at_once_when_the_running_one_ends(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    one_at_a_time.hand_over(unit_of(2, API))
    assert restacks.begun["feature/1"].wait(WAIT)
    ends = one_at_a_time.finished()

    restacks.release("feature/1")

    # No scan and no hand-over: the end of the first is what starts the second.
    assert restacks.begun["feature/2"].wait(WAIT)
    ends.result(timeout=WAIT)
    assert one_at_a_time.running == ["feature/2"]
    assert one_at_a_time.waiting == []


def test_the_restack_that_starts_at_an_end_is_already_running_when_the_end_is_announced(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    one_at_a_time.hand_over(unit_of(2, API))
    assert restacks.begun["feature/1"].wait(WAIT)
    ends = one_at_a_time.finished()

    restacks.release("feature/1")
    ends.result(timeout=WAIT)

    # A loop woken by the end sees the account's next restack running, not still waiting.
    assert "feature/2" in one_at_a_time.running
    assert "feature/2" not in one_at_a_time.waiting


def test_a_waiting_restack_of_the_ended_ones_own_lane_starts_when_it_ends(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    one_at_a_time.hand_over(unit_of(2, WEB))
    assert restacks.begun["feature/1"].wait(WAIT)
    assert one_at_a_time.waiting == ["feature/2"]

    restacks.release("feature/1")

    assert restacks.begun["feature/2"].wait(WAIT)


def test_an_account_that_sets_no_cap_adds_none(made: Made, restacks: Restacks) -> None:
    for lanes in lanes_of(made, restacks, Caps()):
        for number, key in [(1, WEB), (2, API), (3, WEB), (4, API)]:
            lanes.hand_over(unit_of(number, key))
            assert restacks.begun[f"feature/{number}"].wait(WAIT)

        assert len(lanes.running) == 4
        assert lanes.waiting == []


def test_the_default_account_adds_no_cap_though_another_account_is_full(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    one_at_a_time.hand_over(unit_of(2, API))
    one_at_a_time.hand_over(unit_of(3, DOCS))
    one_at_a_time.hand_over(unit_of(4, DOCS))

    assert restacks.begun["feature/3"].wait(WAIT)
    assert restacks.begun["feature/4"].wait(WAIT)
    assert sorted(one_at_a_time.running) == ["feature/1", "feature/3", "feature/4"]
    assert one_at_a_time.waiting == ["feature/2"]


def test_a_full_account_leaves_a_restack_of_another_account_in_the_same_lane_to_start(
    made: Made, restacks: Restacks
) -> None:
    by_id = {"feature/1": "kit", "feature/2": "other", "feature/3": "kit"}
    for lanes in lanes_of(made, restacks, Caps(kit=1), lambda unit: by_id[unit.id]):
        lanes.hand_over(unit_of(3, API))
        assert restacks.begun["feature/3"].wait(WAIT)

        # The head of the lane's queue is of the full account; the next entry is not.
        lanes.hand_over(unit_of(1, WEB))
        lanes.hand_over(unit_of(2, WEB))

        assert restacks.begun["feature/2"].wait(WAIT)
        assert sorted(lanes.running) == ["feature/2", "feature/3"]
        assert lanes.waiting == ["feature/1"]

        restacks.release("feature/3")

        assert restacks.begun["feature/1"].wait(WAIT)


def test_the_skipped_head_keeps_its_place_ahead_of_later_entries_of_its_account(
    made: Made, restacks: Restacks
) -> None:
    by_id = {"feature/1": "kit", "feature/2": "kit", "feature/3": "kit", "feature/9": "other"}
    for lanes in lanes_of(made, restacks, Caps(kit=1), lambda unit: by_id[unit.id]):
        lanes.hand_over(unit_of(1, API))
        assert restacks.begun["feature/1"].wait(WAIT)
        lanes.hand_over(unit_of(2, WEB))
        lanes.hand_over(unit_of(3, WEB))
        lanes.hand_over(unit_of(9, WEB))
        assert restacks.begun["feature/9"].wait(WAIT)
        assert lanes.waiting == ["feature/2", "feature/3"]

        restacks.release("feature/1")

        assert restacks.begun["feature/2"].wait(WAIT)
        assert "feature/3" not in restacks.started


def test_a_projects_own_cap_still_holds_under_a_roomy_account(
    made: Made, restacks: Restacks
) -> None:
    for lanes in lanes_of(made, restacks, Caps(kit=5)):
        for number in (1, 2, 3):
            lanes.hand_over(unit_of(number, WEB))
        lanes.hand_over(unit_of(4, API))

        assert restacks.begun["feature/4"].wait(WAIT)
        assert restacks.begun["feature/2"].wait(WAIT)
        # The lane of WEB has two workers, whatever the account would allow.
        assert sorted(lanes.running) == ["feature/1", "feature/2", "feature/4"]
        assert lanes.waiting == ["feature/3"]


def test_a_projects_own_cap_and_the_accounts_hold_together(made: Made, restacks: Restacks) -> None:
    for lanes in lanes_of(made, restacks, Caps(kit=3)):
        for number, key in [(1, WEB), (2, WEB), (3, WEB), (4, API), (5, API), (6, API)]:
            lanes.hand_over(unit_of(number, key))

        # Two of WEB (its own cap), then one of API (the account's third); 3 waits on its lane,
        # 5 and 6 on the account.
        assert sorted(lanes.running) == ["feature/1", "feature/2", "feature/4"]
        assert sorted(lanes.waiting) == ["feature/3", "feature/5", "feature/6"]


def test_the_lanes_say_whether_a_projects_lane_is_at_its_cap(
    made: Made, restacks: Restacks
) -> None:
    for lanes in lanes_of(made, restacks, Caps()):
        assert not lanes.lane_full(unit_of(1, WEB))
        lanes.hand_over(unit_of(1, WEB))
        assert restacks.begun["feature/1"].wait(WAIT)
        assert not lanes.lane_full(unit_of(2, WEB))

        lanes.hand_over(unit_of(2, WEB))

        assert restacks.begun["feature/2"].wait(WAIT)
        assert lanes.lane_full(unit_of(3, WEB))
        assert not lanes.lane_full(unit_of(3, API))


def test_the_lanes_say_whether_an_account_is_at_its_cap(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    assert not one_at_a_time.account_full(unit_of(1, API))

    one_at_a_time.hand_over(unit_of(1, WEB))
    assert restacks.begun["feature/1"].wait(WAIT)

    # The account's total, over every project of it, though the project of the unit asked about
    # has no restack running; the lane of that project is not full.
    assert one_at_a_time.account_full(unit_of(2, API))
    assert not one_at_a_time.lane_full(unit_of(2, API))
    assert one_at_a_time.at_cap(unit_of(2, API))
    assert not one_at_a_time.account_full(unit_of(3, DOCS))
    assert not one_at_a_time.at_cap(unit_of(3, DOCS))


def test_at_cap_is_true_for_a_full_lane_of_an_account_with_no_cap(
    made: Made, restacks: Restacks
) -> None:
    for lanes in lanes_of(made, restacks, Caps()):
        for number in (1, 2):
            lanes.hand_over(unit_of(number, WEB))
            assert restacks.begun[f"feature/{number}"].wait(WAIT)

        assert not lanes.account_full(unit_of(3, WEB))
        assert lanes.lane_full(unit_of(3, WEB))
        assert lanes.at_cap(unit_of(3, WEB))


def test_an_account_is_no_longer_at_its_cap_once_the_restack_ended(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    assert restacks.begun["feature/1"].wait(WAIT)
    ends = one_at_a_time.finished()

    restacks.release("feature/1")
    ends.result(timeout=WAIT)

    assert not one_at_a_time.account_full(unit_of(2, API))
    assert not one_at_a_time.at_cap(unit_of(2, API))


def test_asking_whether_a_lane_is_full_makes_no_lane(
    one_at_a_time: RestackLanes, made: Made
) -> None:
    assert not one_at_a_time.at_cap(unit_of(1, WEB))

    assert made.by_project == {}


def test_a_restack_that_fails_gives_its_place_to_the_waiting_one(
    tmp_path: Path, restacks: Restacks
) -> None:
    def failing(unit: StoredUnit) -> None:
        restacks(unit)
        if unit.id == "feature/1":
            raise RuntimeError("the move failed")

    failing_made = Made(tmp_path / "locks", failing)
    for lanes in lanes_of(failing_made, restacks, Caps(kit=1)):
        lanes.hand_over(unit_of(1, WEB))
        lanes.hand_over(unit_of(2, API))
        assert restacks.begun["feature/1"].wait(WAIT)

        restacks.release("feature/1")

        assert restacks.begun["feature/2"].wait(WAIT)


def test_a_restack_may_ask_the_lanes_whether_they_are_full_while_it_runs(
    tmp_path: Path, restacks: Restacks
) -> None:
    """A move asking the lanes (the overflow's question) neither deadlocks the lanes nor sees a
    torn count: its own place is already counted."""
    asked: list[bool] = []
    holder: list[RestackLanes] = []

    def asking(unit: StoredUnit) -> None:
        asked.append(holder[0].account_full(unit))
        asked.append(unit.id in holder[0].running)
        restacks(unit)

    asking_made = Made(tmp_path / "locks", asking)
    for lanes in lanes_of(asking_made, restacks, Caps(kit=1)):
        holder.append(lanes)
        lanes.hand_over(unit_of(1, WEB))
        assert restacks.begun["feature/1"].wait(WAIT)

        assert asked == [True, True]


def test_a_done_callback_may_hand_over_to_another_lane_of_the_account(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(
        unit_of(1, WEB), done=lambda ran: one_at_a_time.hand_over(unit_of(2, API))
    )
    assert restacks.begun["feature/1"].wait(WAIT)

    restacks.release("feature/1")

    assert restacks.begun["feature/2"].wait(WAIT)


def test_a_restack_handed_over_twice_to_a_full_account_starts_once(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    one_at_a_time.hand_over(unit_of(1, WEB))
    assert restacks.begun["feature/1"].wait(WAIT)
    one_at_a_time.hand_over(unit_of(2, API))
    one_at_a_time.hand_over(unit_of(2, API))
    ends = one_at_a_time.finished()

    restacks.release("feature/1")
    ends.result(timeout=WAIT)
    restacks.release("feature/2")
    assert drained_within_the_wait(one_at_a_time)

    assert restacks.started == ["feature/1", "feature/2"]


def test_the_cap_holds_under_every_one_waiting_and_ending_in_turn(
    one_at_a_time: RestackLanes, restacks: Restacks
) -> None:
    keys = [WEB, API, WEB, API, WEB, API, WEB, API, WEB]
    for number, key in enumerate(keys, 1):
        one_at_a_time.hand_over(unit_of(number, key))
    assert len(one_at_a_time.running) == 1

    for number in range(len(keys)):
        ends = one_at_a_time.finished()
        (current,) = one_at_a_time.running
        assert restacks.begun[current].wait(WAIT)
        restacks.release(current)
        ends.result(timeout=WAIT)
        # Whichever lane its next restack waits in, exactly one runs until none is left.
        assert len(one_at_a_time.running) == min(1, len(keys) - number - 1)

    assert restacks.most_at_once == 1
    assert sorted(restacks.finished) == sorted(f"feature/{n}" for n in range(1, len(keys) + 1))


class Held:
    """The restacks of the account `kit` held by the test's fake restacks, which note the most of
    them under way at once; the restacks of other accounts are only held."""

    def __init__(self, restacks: Restacks) -> None:
        self.restacks = restacks
        self.mutex = threading.Lock()
        self.now = 0
        self.most = 0

    def __call__(self, unit: StoredUnit) -> None:
        mine = unit.repo == "app"
        if mine:
            with self.mutex:
                self.now += 1
                self.most = max(self.most, self.now)
        try:
            self.restacks(unit)
        finally:
            if mine:
                with self.mutex:
                    self.now -= 1


def test_handing_over_from_many_threads_to_many_lanes_never_exceeds_the_cap_or_stalls(
    tmp_path: Path, restacks: Restacks
) -> None:
    held = Held(restacks)
    projects = [WEB, API, DOCS]
    # `platform` (DOCS) is the default account: only the lanes of `app` share the cap.
    for lanes in lanes_of(Made(tmp_path / "locks", held), restacks, Caps(kit=1)):
        numbers = range(1, 61)

        def hand(each: RestackLanes, chunk: range) -> None:
            for number in chunk:
                each.hand_over(unit_of(number, projects[number % 3]))

        threads = [threading.Thread(target=hand, args=(lanes, numbers[i::4])) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=WAIT)

        # Every restack is held, so more than one of the account's under way would show now: the
        # lanes of `app` have 40 handed over and room for four between them.
        # (A number that is 2 modulo 3 is handed to DOCS, on the default account.)
        mine = [unit for unit in lanes.running if int(unit.split("/")[1]) % 3 != 2]
        assert len(mine) == 1
        # Its worker thread has started, not necessarily entered the move that counts it.
        assert restacks.begun[mine[0]].wait(WAIT)
        assert held.most == 1

        restacks.release_all()

        assert drained_within_the_wait(lanes)
        assert held.most == 1
        assert sorted(restacks.finished) == sorted(f"feature/{n}" for n in numbers)
