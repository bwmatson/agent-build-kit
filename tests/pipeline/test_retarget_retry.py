"""A retarget that did not take is retried each round and escalated after three (spec:
merge-landing).

The host is a stand-in that holds each pull request's base and takes a retarget only when told
to, so the rounds are driven by calling the step directly."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.transport import HostError, RateLimited
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED
from tests.factories import stored_unit

PARENT = "feature/1"
CHILD = "feature/2"
STALE_BASE = f"spec/{PARENT}"
WANTED_BASE = "main"
PULL = 2


class Host:
    """What the forge holds: each unit's pull request base, and a script of whether each retarget
    takes (an exhausted script takes)."""

    def __init__(self, *, takes: list[bool]) -> None:
        self.bases = {CHILD: STALE_BASE}
        self.takes = takes
        self.asked: list[tuple[str, str]] = []
        self.raises: Exception | None = None
        self.resumed: list[tuple[str, str]] = []

    def resume(self, unit: StoredUnit, kind: str, reason: str, feedback: str) -> bool:
        self.resumed.append((unit.id, kind))
        return True

    def base_on_host(self, unit: StoredUnit) -> str | None:
        return self.bases.get(unit.id)

    def retarget(self, unit: StoredUnit, base: str) -> bool:
        self.asked.append((unit.id, base))
        if self.raises is not None:
            raise self.raises
        took = self.takes.pop(0) if self.takes else True
        if took:
            self.bases[unit.id] = base
        return took


def child_behind_a_merged_parent(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit(PARENT, change="feature"),
            stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
        ]
    )
    store.set_state(PARENT, MERGED, pr=1, branch=STALE_BASE)
    store.set_state(CHILD, IN_REVIEW, pr=PULL, branch=f"spec/{CHILD}")
    return store


def run_round(store: UnitStore, host: Host, *, mid_move: bool = False) -> list[str]:
    return events.retry_retargets(
        store,
        base_on_host=host.base_on_host,
        retarget=host.retarget,
        mid_move=lambda unit: mid_move,
        resume=host.resume,
        log=lambda _line: None,
    )


def test_a_unit_whose_base_differs_is_retargeted_each_round_until_it_matches(
    tmp_path: Path,
) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False, True])

    run_round(store, host)
    run_round(store, host)
    run_round(store, host)

    assert host.asked == [(CHILD, WANTED_BASE), (CHILD, WANTED_BASE)]
    assert store.get(CHILD).state == IN_REVIEW


def test_a_unit_held_after_three_failed_rounds_names_the_pull_request_and_the_expected_base(
    tmp_path: Path,
) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False, False, False])

    held = [run_round(store, host) for _ in range(3)]

    unit = store.get(CHILD)
    assert held == [[], [], [CHILD]]
    assert (unit.state, unit.cause) == (HELD, Cause.BASE_NOT_MOVED)
    assert f"#{PULL}" in unit.note
    assert WANTED_BASE in unit.note


def test_two_failed_rounds_do_not_hold_the_unit(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False, False, True])

    run_round(store, host)
    run_round(store, host)

    unit = store.get(CHILD)
    assert (unit.state, unit.base_move_failures) == (IN_REVIEW, 2)


def test_a_success_resets_the_count_of_failed_rounds(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False, False, True, False, False])
    run_round(store, host)
    run_round(store, host)
    run_round(store, host)
    assert store.get(CHILD).base_move_failures == 0

    host.bases[CHILD] = STALE_BASE  # the host puts it back
    run_round(store, host)
    run_round(store, host)

    unit = store.get(CHILD)
    assert (unit.state, unit.base_move_failures) == (IN_REVIEW, 2)


def test_a_unit_whose_thread_is_mid_move_is_left_alone(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False])

    run_round(store, host, mid_move=True)

    assert host.asked == []
    assert store.get(CHILD).base_move_failures == 0


def test_a_unit_already_on_its_base_is_not_retargeted(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[])
    host.bases[CHILD] = WANTED_BASE

    run_round(store, host)

    assert host.asked == []


def test_the_third_failed_round_sends_hold_to_the_unit_s_thread(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False, False, False])

    for _ in range(3):
        run_round(store, host)

    assert host.resumed == [(CHILD, "hold")]


@pytest.mark.parametrize(
    "error",
    [RateLimited("slow down", retry_after=None), HostError("down")],
    ids=["rate-limited", "host-down"],
)
def test_a_host_that_is_down_or_rate_limited_is_not_a_failed_round(
    tmp_path: Path, error: Exception
) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[])
    host.raises = error

    held = [run_round(store, host) for _ in range(3)]

    unit = store.get(CHILD)
    assert held == [[], [], []]
    assert (unit.state, unit.base_move_failures) == (IN_REVIEW, 0)


def test_a_released_hold_gives_the_unit_three_rounds_again(tmp_path: Path) -> None:
    store = child_behind_a_merged_parent(tmp_path)
    host = Host(takes=[False] * 4)
    for _ in range(3):
        run_round(store, host)
    run_round(store, host)  # a round while it is held
    store.set_state(CHILD, IN_REVIEW, pr=PULL)

    run_round(store, host)

    unit = store.get(CHILD)
    assert (unit.state, unit.base_move_failures) == (IN_REVIEW, 1)
