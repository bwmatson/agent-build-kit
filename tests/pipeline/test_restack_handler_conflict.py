"""The stack-move handler leaves a conflict its two resolver steps cannot settle `planned`
with cause `restack_conflict`, the branch where it was, and ports nothing (spec:
restack-adapt; the unit's next run settles it in its build session).

The handler is wired by `build_stack_moves` over a real repository; the agent leaves the
conflict markers in place on both calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.restack_turn_fakes import BRANCH, Rig, rebase_in_progress, run_bounded, sh


def test_two_failed_steps_leave_the_unit_planned_for_its_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    before = sh(rig.repo, "rev-parse", BRANCH)
    rig.act = lambda request: None  # the markers stay

    run_bounded(rig.restack)

    stored = rig.store.get(rig.child.id)
    assert len(rig.requests) == 2, "the two steps, and no third call"
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_CONFLICT)
    assert sh(rig.repo, "rev-parse", BRANCH) == before
    assert not rebase_in_progress(rig.repo)
    assert not rig.temporary_tree().exists()
    assert not any("keep|adapt|retire" in request.prompt for request in rig.requests), "no port"
