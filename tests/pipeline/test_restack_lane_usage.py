"""The lane's resolver is asked of the usage guard like a unit's agent step; a clean move is not.

The usage endpoint is faked at the HTTP boundary (`tests/usage_host.py`) and the guard's own
reading, cache and decision run for real. The unit is moved by the lane `abk tick` builds,
over a repository whose branch conflicts with its base, and the agent is a runtime that
reports a usage window, so the guard is the one asked before it is called.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.pause import PAUSE_MARKER, clear_pause, pause_until
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import asked_of_the_guard, moved_onto_main, restack, tracked_rig
from tests.restack_turn_fakes import (
    BRANCH,
    OLD_BASE,
    Rig,
    commit_file,
    keeps_both,
    rebase_in_progress,
)
from tests.usage_host import Host, payload, refused

MINUTE = timedelta(minutes=1)
CLEAN = "spec/c/3"


class Moving:
    """The pipeline's clock, from now on, moved only by the test."""

    def __init__(self) -> None:
        self.at = datetime.now(UTC)

    def set(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def monotonic(self) -> float:
        return self.at.timestamp()


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: Host) -> Rig:
    return tracked_rig(tmp_path, monkeypatch, host)


def paused(host: Host, rig: Rig) -> None:
    """The session read 99% a moment ago against a pause at 70, and the pipeline paused."""
    host.keep_reading(MINUTE // 2, payload(session=99.0, weekly=5.0))
    pause_until(None, reason="session at 99%", marker=rig.installation.state_dir / PAUSE_MARKER)


def with_room(host: Host) -> None:
    host.keep_reading(MINUTE // 2, payload(session=10.0, weekly=5.0))


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])


def test_under_a_pause_a_clean_restack_is_moved_and_a_conflicting_one_is_aborted_and_deferred(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(rig.repo, "checkout", "-q", "-b", CLEAN, OLD_BASE)
    commit_file(rig.repo, "extra.py", "EXTRA = 1\n")
    git(rig.repo, "checkout", "-q", "main")
    rig.store.upsert([stored_unit("c/3", change="c", branch=CLEAN)])
    rig.store.set_state("c/3", PLANNED, cause=Cause.BASE_CHANGED, branch=CLEAN)
    head = git(rig.repo, "rev-parse", BRANCH)
    paused(host, rig)
    decisions = asked_of_the_guard(monkeypatch)

    restack(rig)

    assert moved_onto_main(rig, CLEAN)
    # Only the conflict needed the agent, so only it was put to the guard, and refused.
    assert [decision.may_start for decision in decisions] == [False]
    assert rig.requests == [], "the agent was called under a pause"
    assert git(rig.repo, "rev-parse", BRANCH) == head
    assert not rebase_in_progress(rig.repo)
    stored = rig.store.get(rig.child.id)
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)


def test_the_guard_is_asked_once_for_each_call_of_the_resolver(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drops_then_keeps(request: AgentRequest) -> None:
        cwd = request.cwd or rig.repo
        if len(rig.requests) == 1:
            (cwd / "markers.py").write_text('markers = ["integration"]\n')
        else:
            keeps_both(cwd)

    rig.act = drops_then_keeps
    rig.prepared()
    with_room(host)
    decisions = asked_of_the_guard(monkeypatch)

    restack(rig)

    assert len(rig.requests) == 2
    assert len(decisions) == 2
    assert moved_onto_main(rig, BRANCH)


def test_a_refused_read_with_room_on_the_estimate_runs_the_resolver_for_the_unit_moved(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    host.keep_reading(89 * MINUTE, payload(session=55.0, weekly=55.0))
    refused(host, cooling=3 * MINUTE)
    decisions = asked_of_the_guard(monkeypatch)

    restack(rig)

    assert [decision.may_start for decision in decisions] == [True]
    assert "estimated" in decisions[0].reason
    assert len(rig.requests) == 1
    assert admitted(host) == [rig.child.id], "the estimate's admission names the unit moved"
    assert moved_onto_main(rig, BRANCH)


def test_a_runtimes_own_refusal_aborts_the_rebase_and_leaves_the_unit_deferred(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuses(request: AgentRequest) -> None:
        raise AgentRateLimited("the model is at its limit")

    rig.act = refuses
    rig.prepared()
    with_room(host)
    head = git(rig.repo, "rev-parse", BRANCH)
    decisions = asked_of_the_guard(monkeypatch)

    restack(rig)

    assert len(decisions) == 1, "the guard is asked before the runtime is"
    assert git(rig.repo, "rev-parse", BRANCH) == head
    assert not rebase_in_progress(rig.repo)
    assert rig.store.get(rig.child.id).cause is Cause.RESTACK_DEFERRED


def test_when_the_pause_ends_the_next_scan_moves_the_unit_asking_the_guard_again(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    paused(host, rig)
    decisions = asked_of_the_guard(monkeypatch)
    marker = rig.installation.state_dir / PAUSE_MARKER

    with cli.build_restack_lane(rig.installation, rig.store) as lane:
        lane.scan(rig.store.all())
        lane.drain()
        assert [decision.may_start for decision in decisions] == [False]

        # Room again, but the pause is still in force: nothing retries on a timer of its own.
        with_room(host)
        lane.scan(rig.store.all())
        lane.drain()
        assert len(decisions) == 1
        assert not moved_onto_main(rig, BRANCH)

        clear_pause(marker)
        lane.scan(rig.store.all())
        lane.drain()

    assert [decision.may_start for decision in decisions] == [False, True]
    assert moved_onto_main(rig, BRANCH)


def test_a_merge_seen_by_the_handler_hands_the_conflicting_child_to_a_gated_lane(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No pause marker stands: the guard's own refusal is what holds the resolver back."""
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    rig.store.upsert([stored_unit("c/2", change="c", depends_on=("c/1",), title=rig.child.title)])
    rig.store.set_state("c/1", IN_REVIEW, pr=1, branch=OLD_BASE)
    rig.store.set_state("c/2", IN_REVIEW, branch=BRANCH)
    head = git(rig.repo, "rev-parse", BRANCH)
    host.keep_reading(MINUTE // 2, payload(session=99.0, weekly=5.0))
    decisions = asked_of_the_guard(monkeypatch)

    with cli.build_restack_lane(rig.installation, rig.store) as lane:
        merged = cli._dispatch(rig.installation, rig.store, lane=lane)("merged", 1, repo="app")
        lane.drain()

    assert merged
    assert [decision.may_start for decision in decisions] == [False]
    assert rig.requests == [], "the agent was called without the guard's say"
    assert git(rig.repo, "rev-parse", BRANCH) == head
    assert not rebase_in_progress(rig.repo)
    stored = rig.store.get("c/2")
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)


def test_a_refusal_is_not_retried_before_its_time_and_is_after_it_with_no_pause_marker(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Moving()
    monkeypatch.setattr(spans, "clock", clock)
    host.keep_reading(MINUTE // 2, payload(session=99.0, weekly=5.0))
    decisions = asked_of_the_guard(monkeypatch)

    with cli.build_restack_lane(rig.installation, rig.store) as lane:
        lane.scan(rig.store.all())
        lane.drain()
        assert [decision.may_start for decision in decisions] == [False]
        assert not (rig.installation.state_dir / PAUSE_MARKER).exists()

        with_room(host)
        lane.scan(rig.store.all())
        lane.drain()
        assert len(decisions) == 1, "retried before the guard expected to allow it"

        resume_at = decisions[0].resume_at
        assert resume_at is not None
        clock.set(resume_at + timedelta(seconds=1))
        lane.scan(rig.store.all())
        lane.drain()

    assert [decision.may_start for decision in decisions] == [False, True]
    assert moved_onto_main(rig, BRANCH)
