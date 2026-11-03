"""What `abk status` can say of the unit-test slots (spec: unit-test-concurrency): who holds each
slot and who waits for one. A waiting run holds a marker of its own that the kernel frees when its
process ends, so a killed waiter is not listed."""

from __future__ import annotations

import threading
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.e2e import LockRecord
from agent_build_kit.pipeline.unit_test_slots import slot_status_lines, unit_test_slot
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
