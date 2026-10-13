"""The lane adds no turn of its own: a restack in it takes the repository's turn for the git
phases the restack names, and not while the resolver edits files.

The turn is the real lock file and the resolver a fake that blocks on an event; what it
shows is read from outside, from threads that are not the lane's.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.runtimes import AgentRequest
from tests.restack_turn_fakes import (
    Rig,
    around_the_resolver,
    keeps_both,
    lock_is_held,
    mark_resolver,
    sh,
    spy_git,
    writes_shared_state,
)

WAIT = 60


def blocking(rig: Rig, at_resolver: threading.Event, release: threading.Event) -> None:
    def resolver(request: AgentRequest) -> None:
        at_resolver.set()
        assert release.wait(WAIT)
        keeps_both(request.cwd or rig.repo)

    rig.act = resolver


def test_another_units_worktree_add_and_push_complete_while_the_lanes_resolver_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    remote = tmp_path / "remote.git"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    sh(rig.repo, "remote", "add", "origin", str(remote))
    sh(rig.repo, "push", "-q", "origin", "main")
    at_resolver, release = threading.Event(), threading.Event()
    blocking(rig, at_resolver, release)
    work = rig.prepared()
    lane = RestackLane(2, move=lambda unit: None, claim=rig.moves["claim"])

    with lane:
        lane.hand_over(rig.child, work)
        assert at_resolver.wait(WAIT)
        assert not lock_is_held(rig.lock)

        other = tmp_path / "other"
        failures: list[BaseException] = []

        def another_unit() -> None:
            try:
                with file_lock(rig.lock):
                    sh(rig.repo, "worktree", "add", "-q", "-b", "spec/d/1", str(other), "main")
                (other / "d.py").write_text("D = 1\n")
                sh(other, "add", "-A")
                sh(other, "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-qm", "d")
                with file_lock(rig.lock):
                    sh(other, "push", "-q", "origin", "spec/d/1")
            except BaseException as error:
                failures.append(error)

        neighbour = threading.Thread(target=another_unit, daemon=True)
        neighbour.start()
        neighbour.join(WAIT)
        finished = not neighbour.is_alive()
        release.set()
        lane.drain()

    assert finished, "another unit waited for the lane's resolver"
    assert not failures
    assert sh(remote, "rev-parse", "spec/d/1")


def test_the_lane_holds_the_turn_for_the_git_phases_and_not_while_the_resolver_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    calls = spy_git(monkeypatch, rig.lock)

    def resolver(request: AgentRequest) -> None:
        mark_resolver(calls, rig.lock, request.cwd or rig.repo)
        keeps_both(request.cwd or rig.repo)

    rig.act = resolver
    work = rig.prepared()
    lane = RestackLane(2, move=lambda unit: None, claim=rig.moves["claim"])

    with lane:
        lane.hand_over(rig.child, work)
        lane.drain()

    before, during, after = around_the_resolver(calls)
    assert not during.held
    assert [call.verb for call in calls if writes_shared_state(call) and not call.held] == []
    assert any(writes_shared_state(call) for call in before)
    assert any(writes_shared_state(call) for call in after)
    assert not lock_is_held(rig.lock)
