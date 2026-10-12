"""An outage while a conflict is being resolved is not a conflict.

The resolver's agent run ends on a network failure: the branch goes back where it was and
the error reaches whoever can park the unit, instead of being written into the unit's
feedback, failing it or recording a restack conflict.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import events, restack
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.runtimes import AgentRequest, NetworkUnavailable
from tests.factories import git
from tests.factories import stored_unit as stored
from tests.pipeline.test_network_outage_parking import UNIT, build_once, fresh_store, outage
from tests.pipeline.test_restack_runtime import conflicting, move  # noqa: F401 — fixture
from tests.runner_fakes import Recorder
from tests.runtimes.stand_in import StandInRuntime

pytestmark = pytest.mark.usefixtures("scripted_engine")


def down(request: AgentRequest) -> None:
    raise outage("strong")


def test_a_resolver_run_that_ends_on_an_outage_leaves_the_branch_and_raises(
    conflicting: Path,  # noqa: F811 — fixture
) -> None:
    before = git(conflicting, "rev-parse", "spec/c/2")
    resolver = partial(restack.claude_resolver, runtime=StandInRuntime(act=down))

    with pytest.raises(NetworkUnavailable):
        move(conflicting, resolve=resolver)

    assert not (conflicting / ".git" / "rebase-merge").exists()
    assert git(conflicting, "rev-parse", "spec/c/2") == before


def test_an_outage_in_prepare_s_restack_parks_the_unit_and_leaves_its_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh_store(tmp_path)
    store.set_feedback(UNIT, "tier 1 failed", source=FeedbackSource.TIER1)
    recorder = Recorder(store)
    recorder.made = 2

    def resolver_down(**kwargs: Any) -> None:
        raise outage("strong")

    build_once(tmp_path, monkeypatch, store, recorder=recorder, restack_onto=resolver_down)

    parked = store.get(UNIT)
    assert parked.state == PLANNED
    assert parked.cause == "network_unavailable"
    assert parked.feedback == "tier 1 failed"
    assert parked.feedback_source == FeedbackSource.TIER1
    assert not [event for event in recorder.events if event.startswith("claude:")], "no adapt run"


def test_a_merge_event_restack_that_meets_an_outage_is_deferred_not_a_conflict(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")

    def refused(*a: Any, **k: Any) -> restack.Moved:
        raise outage("strong")

    restack_child = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=refused,
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: "x",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "d",
        head_of=lambda repo, branch: "h",
    )

    restack_child(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=stored("c/2", pr=2, branch="spec/c/2", approved="h"),
        parent=stored("c/1", pr=1, branch="spec/c/1"),
    )

    last = store.get("c/2").history[-1]
    assert last["state"] == PLANNED
    assert last["cause"] == Cause.RESTACK_DEFERRED
    assert "network outage" in last["note"]
