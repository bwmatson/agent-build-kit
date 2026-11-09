"""The lane's resolver is asked of the usage guard like a unit's agent step; a clean move is not.

The usage endpoint is faked at the HTTP boundary (`tests/usage_host.py`) and the guard's own
reading, cache and decision run for real. The unit is moved by the lane `abk tick` builds,
over a repository whose branch conflicts with its base, and the agent is a runtime that
reports a usage window, so the guard is the one asked before it is called.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import (
    asked_of_the_guard,
    tracked_rig,
)
from tests.restack_turn_fakes import (
    BRANCH,
    OLD_BASE,
    Rig,
    rebase_in_progress,
)
from tests.usage_host import Host, payload

MINUTE = timedelta(minutes=1)
CLEAN = "spec/c/3"


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
        merged = cli.dispatch_for(rig.installation, rig.store, lane=lane)("merged", 1, repo="app")
        lane.drain()

    assert merged
    assert [decision.may_start for decision in decisions] == [False]
    assert rig.requests == [], "the agent was called without the guard's say"
    assert git(rig.repo, "rev-parse", BRANCH) == head
    assert not rebase_in_progress(rig.repo)
    stored = rig.store.get("c/2")
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
