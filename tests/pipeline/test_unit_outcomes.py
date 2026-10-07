"""A unit's outcome, its escalation and its state are defined values, and an unsupported
toolchain has its own exception."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import spans, stack_runner
from agent_build_kit.pipeline.stack_runner import Escalation, RunStatus, UnitOutcome
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import (
    UnitState,
)
from agent_build_kit.profiles import base, node_npm
from tests.factories import unit
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
        "ok",
        "waiting",
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
        "planned",
        "running",
        "in_review",
        "merged",
        "closed",
        "failed",
        "held",
        "satisfied",
        "unplanned",
    }


def test_a_store_written_with_plain_state_strings_loads_unit_states(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit()])
    assert '"planned"' in path.read_text(), "on disk a state is a plain string"

    store = UnitStore(path)

    assert isinstance(store.get(unit().id).state, UnitState)
    with pytest.raises(ValueError):
        store.set_state(unit().id, "bogus")  # type: ignore[arg-type]
    assert store.get(unit().id).state is UnitState.PLANNED


def test_every_node_span_records_an_outcome_from_the_enum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[object] = []
    real = spans.record_span

    def record(*args: Any, **kwargs: Any) -> None:
        if "outcome" in kwargs:
            recorded.append(kwargs["outcome"])
        real(*args, **kwargs)

    monkeypatch.setattr(spans, "record_span", record)

    tick(tmp_path, fresh(tmp_path))

    assert recorded
    assert all(isinstance(outcome, UnitOutcome) for outcome in recorded)


def test_a_profile_the_framework_does_not_implement_raises_it() -> None:
    with pytest.raises(base.ProfileUnsupported):
        node_npm.NodeNpmProfile().lint_command("main")
