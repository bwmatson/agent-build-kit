"""What `abk status` can say of the unit-test slots (spec: unit-test-concurrency): who holds each
slot and who waits for one. A waiting run holds a marker of its own that the kernel frees when its
process ends, so a killed waiter is not listed."""

from __future__ import annotations

import threading
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.e2e import LockRecord
from agent_build_kit.pipeline.unit_test_slots import slot_status_lines, unit_test_slot
from tests.fake_clock import START, install
from tests.unit_test_slot_fakes import live_waiter, waiting_run
from tests.waiting import wait_for


def test_with_no_limit_there_is_nothing_to_say(tmp_path: Path) -> None:
    assert slot_status_lines(tmp_path, None) == []


def test_free_slots_are_said_to_be_free(tmp_path: Path) -> None:
    [line] = slot_status_lines(tmp_path, 2)

    assert line.startswith("unit-test slots (2 at once):")
    assert "slot 1 free" in line and "slot 2 free" in line
    assert "waiting" not in line


def test_each_holder_is_named_with_its_slot(tmp_path: Path) -> None:
    with ExitStack() as held:
        held.enter_context(unit_test_slot(tmp_path, 2, holder="a/1"))
        held.enter_context(unit_test_slot(tmp_path, 2, holder="b/1"))

        [line] = slot_status_lines(tmp_path, 2)

    assert "slot 1 held by a/1" in line and "slot 2 held by b/1" in line


def test_a_waiting_run_is_named(tmp_path: Path) -> None:
    release = threading.Event()
    waiting_started = threading.Event()

    def wait_for_a_slot() -> None:
        with unit_test_slot(
            tmp_path, 1, holder="c/1", on_wait=lambda message: waiting_started.set()
        ):
            release.wait(timeout=20)

    with unit_test_slot(tmp_path, 1, holder="a/1"):
        thread = threading.Thread(target=wait_for_a_slot, daemon=True)
        thread.start()
        assert waiting_started.wait(timeout=20)
        [line] = slot_status_lines(tmp_path, 1)
    wait_for(
        lambda: "held by c/1" in slot_status_lines(tmp_path, 1)[0], what="c/1 to hold the slot"
    )
    release.set()
    thread.join(timeout=20)

    assert "waiting: c/1" in line
    assert "slot 1 held by a/1" in line


def test_a_waiter_marker_left_by_a_process_that_is_gone_is_not_listed(tmp_path: Path) -> None:
    stale = LockRecord(unit="ghost/1", pid=1, since=datetime.now(UTC).isoformat())
    (tmp_path / "unit-test-waiting-stale.lock").write_text(stale.model_dump_json() + "\n")

    [line] = slot_status_lines(tmp_path, 1)

    assert "ghost/1" not in line


def test_a_waiter_marker_is_gone_once_the_wait_ends(tmp_path: Path) -> None:
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="a/1"))
    told: list[str] = []
    got = threading.Event()

    def take() -> None:
        with unit_test_slot(tmp_path, 1, holder="b/1", on_wait=told.append):
            got.set()

    thread = threading.Thread(target=take, daemon=True)
    thread.start()
    wait_for(lambda: bool(told), what="the wait")
    holder.close()
    assert got.wait(timeout=20)
    thread.join(timeout=20)

    assert list(tmp_path.glob("unit-test-waiting-*")) == []


# The waiting units are listed in the order they will be served.


def waiting_part(line: str) -> str:
    return line.split("waiting: ", 1)[1]


def test_the_waiting_units_are_listed_by_rank_then_time_not_by_marker_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    early, late = START - timedelta(minutes=30), START - timedelta(minutes=5)
    # file names sort the opposite way to the order of service
    with ExitStack() as markers:
        for token, unit, since, rank in (
            ("1-aaaa", "unranked/1", early, None),
            ("2-bbbb", "lazy-late/1", late, (2, 4)),
            ("3-cccc", "lazy-early/1", early, (2, 4)),
            ("4-dddd", "urgent/1", late, (0, 2)),
        ):
            markers.enter_context(live_waiter(tmp_path, token, unit, since=since, rank=rank))

        [line] = slot_status_lines(tmp_path, 1)

    names = [part.split(" for ")[0] for part in waiting_part(line).split(", ")]
    assert names == ["urgent/1", "lazy-early/1", "lazy-late/1", "unranked/1"]


def test_waiters_of_equal_rank_and_time_are_listed_by_marker_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with ExitStack() as markers:
        for token, unit in (("9-zzzz", "z/1"), ("1-aaaa", "a/1")):
            markers.enter_context(live_waiter(tmp_path, token, unit, since=START, rank=(2, 4)))

        [line] = slot_status_lines(tmp_path, 1)

    assert waiting_part(line).index("a/1") < waiting_part(line).index("z/1")


def test_the_listing_matches_the_order_the_waiters_are_served(tmp_path: Path) -> None:
    order: list[str] = []
    with ExitStack() as stack:
        with unit_test_slot(tmp_path, 1, holder="holder/1"):
            for unit, rank in (("lazy/1", (2, 4)), ("urgent/1", (0, 2))):
                run = stack.enter_context(waiting_run(tmp_path, unit, rank=rank, order=order))
                run.until_waiting(tmp_path, unit)
            [line] = slot_status_lines(tmp_path, 1)
        wait_for(lambda: len(order) == 1, what="the first waiter to take the slot")

    assert waiting_part(line).index("urgent/1") < waiting_part(line).index("lazy/1")
    assert order == ["urgent/1"]
