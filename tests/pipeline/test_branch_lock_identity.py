"""A branch lock names its holder by pid and start time, so a reused pid is not a live holder."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from agent_build_kit.pipeline.locks import proc_identity
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_held, branch_lock

BRANCH = "spec/change/1"
RACERS = 8


def _lock_file(locks: Path) -> Path:
    return locks / "spec_change_1.lock"


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_a_lock_records_pid_and_start_time(tmp_path: Path) -> None:
    locks = tmp_path / "locks"

    with branch_lock(BRANCH, root=locks):
        record = json.loads(_lock_file(locks).read_text())

    assert record["pid"] == os.getpid()
    assert record["started"] == proc_identity(os.getpid())


def test_a_live_pid_with_another_start_time_is_stale_and_taken_over(tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    _lock_file(locks).write_text(json.dumps({"pid": os.getpid(), "started": "not-this-process"}))

    assert not branch_held(BRANCH, root=locks)
    with branch_lock(BRANCH, root=locks):
        record = json.loads(_lock_file(locks).read_text())

    assert record["started"] == proc_identity(os.getpid())


def test_a_live_holder_with_a_matching_start_time_keeps_the_lock(tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    _lock_file(locks).write_text(
        json.dumps({"pid": os.getpid(), "started": proc_identity(os.getpid())})
    )

    assert branch_held(BRANCH, root=locks)
    with pytest.raises(BranchBusy):
        with branch_lock(BRANCH, root=locks):
            pass


def test_an_old_format_lock_is_honoured_while_its_process_lives(tmp_path: Path) -> None:
    """A lock written before start times were recorded holds only a pid."""
    locks = tmp_path / "locks"
    locks.mkdir()
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    try:
        _lock_file(locks).write_text(json.dumps({"pid": child.pid, "branch": BRANCH}))
        assert branch_held(BRANCH, root=locks)
        with pytest.raises(BranchBusy):
            with branch_lock(BRANCH, root=locks):
                pass
    finally:
        child.communicate()

    with branch_lock(BRANCH, root=locks):
        record = json.loads(_lock_file(locks).read_text())
    assert record["started"] == proc_identity(os.getpid())


def test_racers_for_a_stale_lock_never_both_hold_it(tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    _lock_file(locks).write_text(json.dumps({"pid": _dead_pid(), "started": "gone"}))

    start = threading.Barrier(RACERS)
    settled = threading.Event()
    guard = threading.Lock()
    holders: list[str] = []
    losers: list[str] = []
    started: list[str] = []

    def race() -> None:
        start.wait()
        try:
            with branch_lock(BRANCH, root=locks):
                with guard:
                    holders.append("held")
                    started.append(json.loads(_lock_file(locks).read_text())["started"])
                # Hold until every other racer has been turned away (or the wait gives out).
                settled.wait(timeout=10)
        except BranchBusy:
            with guard:
                losers.append("busy")
                if len(losers) >= RACERS - 1:
                    settled.set()

    threads = [threading.Thread(target=race) for _ in range(RACERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(holders) == 1
    assert len(losers) == RACERS - 1
    assert started == [proc_identity(os.getpid())]


def test_a_lock_recording_no_start_time_is_judged_by_its_pid_alone(tmp_path: Path) -> None:
    """A host that cannot read start times records `started: null`; a dead holder is not alive."""
    locks = tmp_path / "locks"
    locks.mkdir()
    _lock_file(locks).write_text(json.dumps({"pid": _dead_pid(), "started": None}))

    assert not branch_held(BRANCH, root=locks)
    with branch_lock(BRANCH, root=locks):
        assert json.loads(_lock_file(locks).read_text())["pid"] == os.getpid()


def test_a_live_pid_recording_no_start_time_still_holds_the_lock(tmp_path: Path) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    _lock_file(locks).write_text(json.dumps({"pid": os.getpid(), "started": None}))

    assert branch_held(BRANCH, root=locks)
    with pytest.raises(BranchBusy), branch_lock(BRANCH, root=locks):
        pass
