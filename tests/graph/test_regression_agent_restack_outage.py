"""An agent that cannot run while a restack records a failure defers the restack; it is not a
fault of the branch (spec: regression-agent).

`on_flake` is a stand-in that raises what the agent step raises when the agent cannot run.
"""

from __future__ import annotations

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.events import RestackOutcome
from agent_build_kit.pipeline.flakes import FailedOnBase, FlakeFound
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    NetworkUnavailable,
    ServiceUnavailable,
)
from tests.factories import stored_unit
from tests.graph.test_failed_on_base_callers import FAILING
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked

WORDS = "the agent could not run"
OUTAGES = {
    "rate-limit": AgentRateLimited(WORDS),
    "interrupted": AgentInterrupted(WORDS),
    "network": NetworkUnavailable(WORDS, strength="strong", host="api.example.com"),
    "service": ServiceUnavailable(WORDS, status=529),
}


@pytest.mark.parametrize("outage", OUTAGES.values(), ids=OUTAGES.keys())
@pytest.mark.parametrize("raised", ["scoped", "failed-on-base"])
def test_an_agent_that_cannot_run_defers_the_restack_and_pushes_nothing(
    installation: Installation, outage: Exception, raised: str
) -> None:
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    pushed: list[str] = []

    def checks(**kwargs: object):
        if raised == "scoped":
            raise FlakeFound((flaked(),), scoped=True)
        raise FailedOnBase((FAILING,))

    def cannot_run(unit, flake, *, wait=True):
        raise outage

    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        unit_test=checks,
        on_flake=cannot_run,
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    outcome = restack(
        branch="spec/feature/1",
        old_base="spec/parent/1",
        new_base="main",
        child=child,
        parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
    )

    assert outcome is RestackOutcome.DEFERRED
    stored = store.get("feature/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
    assert "deferred" in stored.note
    assert pushed == []
