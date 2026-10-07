"""A unit's outcome, its escalation and its state are defined values, and an unsupported
toolchain has its own exception."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import stack_runner
from agent_build_kit.pipeline.stack_runner import Escalation, RunStatus, UnitOutcome
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
)
from agent_build_kit.profiles import base, node_npm
from tests.graph_driver import fresh, tick


def test_the_outcomes_are_the_fixed_set() -> None:
    assert {outcome.value for outcome in UnitOutcome} == {
        "open",
        "paused",
        "held",
        "satisfied",
        "failed",
        "interrupted",
        "rate_limited",
        "skipped",
        "error",
    }


def test_every_run_status_is_an_outcome() -> None:
    assert {status.value for status in RunStatus} <= {outcome.value for outcome in UnitOutcome}


def test_a_run_over_the_graph_ends_in_an_outcome(tmp_path: Path) -> None:
    outcome = tick(tmp_path, fresh(tmp_path))

    assert isinstance(outcome.status, UnitOutcome)
    assert outcome.status is UnitOutcome.OPEN


def test_the_escalations_are_the_fixed_set_and_the_bare_tuple_is_gone() -> None:
    assert {escalation.value for escalation in Escalation} == {"class", "disagreement"}
    assert not hasattr(stack_runner, "ESCALATIONS")


def test_the_unit_states_are_the_fixed_set() -> None:
    assert {state.value for state in UnitState} == {
        PLANNED,
        RUNNING,
        IN_REVIEW,
        MERGED,
        CLOSED,
        FAILED,
        HELD,
        SATISFIED,
    }


def test_a_profile_the_framework_does_not_implement_raises_it() -> None:
    with pytest.raises(base.ProfileUnsupported):
        node_npm.NodeNpmProfile().lint_command("main")
