"""A build that made nothing is held, not satisfied, when its builder reported the work blocked
(spec: builder-blocked-holds). Driven at the build's public seam with the fakes the satisfied
tests use."""

from __future__ import annotations

import json
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
        ("BLOCKED: X\nprose\nBLOCKED: X\nBLOCKED: Y", "BLOCKED: X|BLOCKED: Y"),
        ("it was not BLOCKED: no line starts so", ""),
    ],
)
def test_the_blocked_lines_of_an_account_are_kept_once_each_without_markup(
    account: str, expected: str
) -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker")

    update = blocked_update(state, account)

    assert "|".join(update.get("blocked_lines", ())) == expected


def test_a_later_account_adds_to_the_earlier_blocked_lines() -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker", blocked_lines=("BLOCKED: X",))

    assert blocked_update(state, "BLOCKED: Y") == {"blocked_lines": ("BLOCKED: X", "BLOCKED: Y")}


def test_an_empty_account_keeps_the_earlier_blocked_lines() -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker", blocked_lines=("BLOCKED: X",))

    assert blocked_update(state, "") == {}


def test_a_line_holding_a_semicolon_reported_twice_is_kept_once() -> None:
    line = "BLOCKED: X does not exist; group 1 needs it"
    state = UnitRun(unit_id=UNIT, change="add-marker")

    first = blocked_update(state, line)
    again = UnitRun(unit_id=UNIT, change="add-marker", **first)

    assert first == {"blocked_lines": (line,)}
    assert blocked_update(again, line) == {}


def test_a_blocked_line_in_the_json_summary_of_a_rework_answer_is_found() -> None:
    state = UnitRun(unit_id=UNIT, change="add-marker")
    answer = 'Nothing to change.\n{"replies": [], "summary": "BLOCKED: X does not exist"}'

    assert blocked_update(state, answer) == {"blocked_lines": ("BLOCKED: X does not exist",)}


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


@pytest.mark.parametrize("blocked", [True, False], ids=["blocked", "not-blocked"])
def test_a_rework_that_makes_nothing_is_held_only_when_its_json_answer_reports_it_blocked(
    tmp_path: Path, blocked: bool
) -> None:
    missing = "SqlCheckpointSaver does not exist"
    summary = f"BLOCKED: {missing}; group 1 needs it" if blocked else "Nothing to change."
    answer = f"I made no change.\n\n{json.dumps({'replies': [], 'summary': summary})}"
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0, rework_answer=answer)
    store = recorder.store
    store.set_state(unit().id, PLANNED, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "please double-check the edge case")

    outcome = build(tmp_path, recorder, graph=[store.get(unit().id)], **empty_branch())

    stored = store.get(unit().id)
    assert outcome.status == ("held" if blocked else "satisfied"), outcome.detail
    assert (stored.state == HELD) is blocked
    assert (missing in stored.history[-1]["note"]) is blocked
    assert bool(recorder.closed) is not blocked
