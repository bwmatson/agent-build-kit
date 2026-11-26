"""A build that made nothing is held, not satisfied, when its builder reported the work blocked
(spec: builder-blocked-holds). Driven at the build's public seam with the fakes the satisfied
tests use."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, PLANNED, SATISFIED, branch_name
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_remaining_paths import empty_branch, fresh, tasks_file
from tests.factories import unit
from tests.graph.branch_fakes import UNIT, built

TASKS = ("meta", "openspec", "changes", "add-marker", "tasks.md")


def test_a_build_that_made_nothing_is_held_when_the_implementation_agent_reports_it_blocked(
    tmp_path: Path,
) -> None:
    missing = "SqlPersist does not exist"
    account = f"Group 2 cannot be built yet.\n\nBLOCKED: {missing} in this tree; group 2 needs it"

    recorder, outcome, _ = built(tmp_path, silent_groups=(1, 2, 3), accounts={"2": account})

    stored = recorder.store.get(UNIT)
    assert outcome.status == "held", outcome.detail
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert stored.state != SATISFIED
    assert missing in stored.history[-1]["note"]
    assert recorder.closed == []
    assert "- [x]" not in tmp_path.joinpath(*TASKS).read_text()


def test_a_rework_that_makes_nothing_is_held_when_the_builder_reports_it_blocked(
    tmp_path: Path,
) -> None:
    missing = "SqlCheckpointSaver does not exist"
    tasks_file(tmp_path)
    recorder = fresh(
        tmp_path,
        commits_from_impl=0,
        rework_answer=f"BLOCKED: {missing}; group 1 needs it",
    )
    store = recorder.store
    store.set_state(unit().id, PLANNED, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "please double-check the edge case")

    outcome = build(tmp_path, recorder, graph=[store.get(unit().id)], **empty_branch())

    stored = store.get(unit().id)
    assert outcome.status == "held", outcome.detail
    assert stored.state == HELD
    assert missing in stored.history[-1]["note"]
    assert recorder.closed == []
