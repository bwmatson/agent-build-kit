"""A review round is a span with a cause, and a usage-paused unit reads as paused
(spec: unit-timeline-is-recorded)."""

from __future__ import annotations

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.spans import Mark, record_span
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.vocabulary import effective_state
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install, span_lines


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.mark.parametrize("cause", ["review", "check", "conflict"])
def test_a_review_round_is_a_span_with_its_cause(
    workspace: Installation, clock: FakeClock, cause: str
) -> None:
    mark = Mark()
    clock.advance(240)

    record_span(
        mark,
        print,
        unit="add-marker/1",
        change="add-marker",
        node="rework",
        round_number=2,
        cause=cause,
    )

    (span,) = span_lines(workspace)
    assert span["cause"] == cause
    assert (span["node"], span["round"], span["duration_ms"]) == ("rework", 2, 240_000)


def test_a_usage_paused_unit_displays_as_paused_with_its_stored_state_unchanged() -> None:
    unit = stored_unit(state=RUNNING, branch="spec/add-marker/1")

    assert effective_state(unit, [unit], usage_paused=True) == "paused"
    assert effective_state(unit, [unit]) == RUNNING
    assert unit.state == RUNNING
