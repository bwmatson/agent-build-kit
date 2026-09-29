"""The tier 2 gate: the real local stack, one run at a time.

Tier 2 tests need the gateway, the database, the event bus, the browser and
the router as they actually run on this host, on fixed ports. There is one
of each, so two tier 2 runs at once would interfere — they queue behind a
single lock, whatever the concurrency setting says (docs/architecture.md).

The result gates the push: tier 2 passes, then the branch is pushed, then the
status is posted on the commit that was tested. That order matters — GitHub
only accepts a status for a commit it already has.
"""

import threading
import time
from pathlib import Path

import pytest

from agent_build_kit.pipeline.tier2 import (
    STATUS_CONTEXT,
    Tier2Result,
    build_snapshot,
    post_status,
    stack_lock,
)
from tests.forges.stand_in import StandInForge


def test_a_second_run_waits_for_the_first(tmp_path: Path) -> None:
    """Not fail-fast, unlike the per-branch locks: tier 2 is a queue, because
    the second unit's tests are just as valid, they simply can't run yet."""
    lock = tmp_path / "tier2.lock"
    order: list[str] = []

    def hold() -> None:
        with stack_lock(lock):
            order.append("first-in")
            time.sleep(0.2)
            order.append("first-out")

    def wait() -> None:
        time.sleep(0.05)
        with stack_lock(lock):
            order.append("second-in")

    threads = [threading.Thread(target=hold), threading.Thread(target=wait)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert order == ["first-in", "first-out", "second-in"]


def test_waiting_too_long_gives_up_rather_than_hanging(tmp_path: Path) -> None:
    """An unattended run that blocks forever is indistinguishable from a
    crashed one, and holds its worktree the whole time."""
    lock = tmp_path / "tier2.lock"

    with stack_lock(lock):
        with pytest.raises(TimeoutError):
            with stack_lock(lock, timeout=0.1):
                pass


def test_the_lock_is_released_when_a_run_blows_up(tmp_path: Path) -> None:
    """One crashed run must not wedge the tier for everything after it."""
    lock = tmp_path / "tier2.lock"

    with pytest.raises(ValueError):  # noqa: PT012 — the raise is the point
        with stack_lock(lock):
            raise ValueError("boom")

    with stack_lock(lock, timeout=0.1):
        pass


def result(**overrides) -> Tier2Result:
    defaults: dict = {
        "sha": "abc1234def",
        "passed": 4,
        "failed": 0,
        "skipped": 1,
        "duration_seconds": 12.5,
        "command": "uv run pytest -m local_stack",
        "output": "4 passed, 1 skipped in 12.50s",
        "stack_versions": {"platform": "9f2a1c0", "model alias": "local"},
    }
    return Tier2Result(**{**defaults, **overrides})


def test_the_snapshot_says_what_ran_and_against_what() -> None:
    """A snapshot nobody can check is decoration. It has to name the commit,
    the command, the counts and the stack it ran against."""
    snapshot = build_snapshot(result())

    assert "abc1234" in snapshot
    assert "uv run pytest -m local_stack" in snapshot
    assert "4 passed" in snapshot
    assert "12.5" in snapshot
    assert "platform" in snapshot
    assert "9f2a1c0" in snapshot


def test_the_snapshot_folds_the_full_output_away() -> None:
    """Useful when a reviewer wants it, invisible when they don't."""
    snapshot = build_snapshot(result(output="x" * 50))

    assert "<details>" in snapshot
    assert "x" * 50 in snapshot


def test_a_failing_run_is_not_a_snapshot_to_publish() -> None:
    """Tier 2 gates the push, so a failure means nothing is pushed and there
    is nothing to attach a snapshot to."""
    assert not result(failed=2).ok
    assert result().ok


def test_the_status_is_posted_for_the_sha_that_was_tested() -> None:
    """A snapshot is only valid for the commit it ran against: a restack
    changes the SHA, and the old result says nothing about the new one."""
    forge = StandInForge()

    post_status(forge, forge.repo_id(), result())

    [posted] = forge.statuses
    assert posted["sha"] == "abc1234def"
    assert posted["context"] == STATUS_CONTEXT
    assert posted["ok"]
    assert "0 failed" in posted["description"]


def test_a_failed_run_posts_a_failure_status_when_asked() -> None:
    """Only reachable for a re-run of an already-pushed commit — the usual
    path never pushes a failing unit at all."""
    forge = StandInForge()

    post_status(forge, forge.repo_id(), result(failed=1))

    assert not forge.statuses[0]["ok"]
