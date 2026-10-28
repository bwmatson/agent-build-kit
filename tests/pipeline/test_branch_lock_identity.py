"""A branch lock names its holder by pid and process start time.

A pid alone can be reused by an unrelated process, so a lock whose pid is alive but whose
recorded start time differs from that process's is stale. A lock written before the start
time was recorded (a bare pid) is still honoured while its process lives.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.file_lock import ps_start_time
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_held,
    branch_lock,
    lock_holder_gone,
)
from tests.branch_lock_fakes import dead_pid

BRANCH = "spec/feature/1"
RACERS = 4


def lock_file(root: Path) -> Path:
    (path,) = root.glob("*.lock")
    return path


def write_lock(root: Path, content: str) -> None:
    """Put `content` where `branch_lock` keeps this branch's lock, found by taking it once."""
    if not any(root.glob("*.lock")):
        with branch_lock(BRANCH, root=root):
            path = lock_file(root)
    else:
        path = lock_file(root)
    path.write_text(content)


def test_a_lock_records_the_pid_and_start_time_of_its_holder(tmp_path):
    with branch_lock(BRANCH, root=tmp_path):
        record = json.loads(lock_file(tmp_path).read_text())

    assert record["pid"] == os.getpid()
    assert record["started"]


def test_a_live_holder_keeps_its_lock(tmp_path):
    with branch_lock(BRANCH, root=tmp_path):
        recorded = json.loads(lock_file(tmp_path).read_text())
        assert recorded["started"]
        with pytest.raises(BranchBusy):
            with branch_lock(BRANCH, root=tmp_path):
                pass
        assert branch_held(BRANCH, root=tmp_path)
        assert lock_holder_gone(BRANCH, root=tmp_path) is False


def test_a_lock_whose_pid_was_reused_by_another_process_is_stale(tmp_path):
    write_lock(tmp_path, json.dumps({"pid": os.getpid(), "started": "0", "branch": BRANCH}))

    assert lock_holder_gone(BRANCH, root=tmp_path) is True
    assert not branch_held(BRANCH, root=tmp_path)


def test_a_stale_lock_is_taken_over_with_the_new_holders_identity(tmp_path):
    write_lock(tmp_path, json.dumps({"pid": os.getpid(), "started": "0", "branch": BRANCH}))

    with branch_lock(BRANCH, root=tmp_path):
        record = json.loads(lock_file(tmp_path).read_text())

    assert record["pid"] == os.getpid()
    assert record["started"] not in ("", "0")


def test_a_lock_of_another_host_is_held_whatever_its_start_time_says(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(host, "this_host", lambda: "box")
    write_lock(
        tmp_path,
        json.dumps({"pid": os.getpid(), "started": "0", "host": "other", "branch": BRANCH}),
    )

    assert lock_holder_gone(BRANCH, root=tmp_path) is False
    with pytest.raises(BranchBusy):
        with branch_lock(BRANCH, root=tmp_path):
            pass


def test_a_lock_holding_only_a_pid_is_honoured_while_its_process_lives(tmp_path):
    write_lock(tmp_path, json.dumps({"pid": os.getpid()}))
    with pytest.raises(BranchBusy):
        with branch_lock(BRANCH, root=tmp_path):
            pass

    write_lock(tmp_path, str(os.getpid()))
    with pytest.raises(BranchBusy):
        with branch_lock(BRANCH, root=tmp_path):
            pass
    assert branch_held(BRANCH, root=tmp_path)


def test_a_lock_holding_only_the_pid_of_a_gone_process_is_taken_over(tmp_path):
    write_lock(tmp_path, str(dead_pid()))
    assert lock_holder_gone(BRANCH, root=tmp_path) is True

    with branch_lock(BRANCH, root=tmp_path):
        assert json.loads(lock_file(tmp_path).read_text())["started"]


def test_ps_names_a_process_by_the_same_start_time_in_any_zone_and_locale(monkeypatch):
    if shutil.which("ps") is None:
        pytest.skip("no ps on this host")
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_TIME", "de_DE.UTF-8")
    first = ps_start_time(os.getpid())
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_TIME", "ja_JP.UTF-8")
    second = ps_start_time(os.getpid())

    assert first is not None
    assert first == second


def test_racing_for_a_stale_lock_never_gives_it_to_two_holders(tmp_path):
    """Probabilistic: it catches a missing claim only when the racers interleave inside the
    window between judging the lock stale and creating the new one."""
    write_lock(tmp_path, json.dumps({"pid": os.getpid(), "started": "0", "branch": BRANCH}))
    start = threading.Barrier(RACERS)
    release = threading.Event()
    outcomes: queue.Queue[str] = queue.Queue()

    def race() -> None:
        start.wait(timeout=10)
        try:
            with branch_lock(BRANCH, root=tmp_path):
                outcomes.put("won")
                release.wait(timeout=10)
        except BranchBusy:
            outcomes.put("busy")

    threads = [threading.Thread(target=race) for _ in range(RACERS)]
    for thread in threads:
        thread.start()
    try:
        results = [outcomes.get(timeout=10) for _ in range(RACERS)]
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=10)

    assert results.count("won") == 1
