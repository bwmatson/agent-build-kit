"""A build that made nothing is held, not satisfied, when its builder reported the work blocked
(spec: builder-blocked-holds). Driven at the build's public seam with the fakes the satisfied
tests use."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.nodes import blocked_update
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, PLANNED, branch_name
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_remaining_paths import empty_branch, fresh, tasks_file
from tests.factories import unit
from tests.graph.branch_fakes import UNIT, built


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        ("BLOCKED: X is missing", "BLOCKED: X is missing"),
        ("  - BLOCKED: X is missing", "BLOCKED: X is missing"),
        ("1. BLOCKED: X is missing", "BLOCKED: X is missing"),
        ("- **BLOCKED:** X is missing", "BLOCKED: X is missing"),
        ("**BLOCKED: X is missing", "BLOCKED: X is missing"),
        ("BLOCKED: X\nprose\nBLOCKED: X\nBLOCKED: Y", "BLOCKED: X; BLOCKED: Y"),
        ("it was not BLOCKED: no line starts so", ""),
    ],
)
def test_the_blocked_lines_of_an_account_are_kept_once_each_without_markup(
    account: str, expected: str
) -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker")

    update = blocked_update(state, account)

    assert update.get("blocked_lines", "") == expected


def test_a_later_account_adds_to_the_earlier_blocked_lines_and_an_empty_one_keeps_them() -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker", blocked_lines="BLOCKED: X")

    assert blocked_update(state, "BLOCKED: Y") == {"blocked_lines": "BLOCKED: X; BLOCKED: Y"}
    assert blocked_update(state, "") == {}


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
