"""A model service answering 5xx or 529 parks the unit, up to a cap.

The status is evidence on its own, so the probe is never asked. Such a parking counts in a
row, and at `global_limits.service_unavailable_attempts` the next failure fails the unit with its
error text and step. A step that completes, or a move to review, ends the row; a parking
the probe sorted is not counted and not capped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.metric_records import InstrumentKind
from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED
from agent_build_kit.runtimes import ServiceUnavailable
from tests.leftovers_driver import step_of
from tests.pipeline.test_network_outage_parking import (
    UNIT,
    Probe,
    build_once,
    fresh_store,
    outage,
    raises_in_implement,
    thread_state,
)
from tests.runner_fakes import Recorder, rejecting

pytestmark = pytest.mark.usefixtures("scripted_engine")

WORDS = "API Error: 529 overloaded_error"
CAP = {"global_limits": {"service_unavailable_attempts": 3}}


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


def overloaded(status: int = 529) -> ServiceUnavailable:
    return ServiceUnavailable(WORDS, status=status)


def park_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: UnitStore, error: Exception
) -> None:
    build_once(
        tmp_path,
        monkeypatch,
        store,
        config=CAP,
        run=raises_in_implement(error, ""),
    )


def test_a_status_parks_the_unit_without_asking_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    store.set_feedback(UNIT, "rename the marker", source=FeedbackSource.REVIEW)

    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(overloaded(), "rework"))

    stored = store.get(UNIT)
    assert (stored.state, stored.cause, stored.step) == (PLANNED, "service_unavailable", "rework")
    assert "overloaded_error" in stored.note
    assert stored.feedback == "rename the marker"
    assert stored.feedback_source == FeedbackSource.REVIEW
    assert stored.branch
    assert probe.asked == []


def test_the_status_that_parks_the_unit_is_not_counted_as_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    """The status comes on the second fix of the checks a rework broke, after one review round."""
    outcomes: list[str] = []
    real_record = cli.emit_metric

    def record(
        instrument: InstrumentKind, name: str, value: float, log: Any, **labels: Any
    ) -> None:
        if name == "abk.unit.duration":
            outcomes.append(labels["outcome"])
        real_record(instrument, name, value, log, **labels)

    monkeypatch.setattr(cli, "emit_metric", record)
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    recorder.unit_test_results = [
        (True, ""),
        (False, "E501 line too long"),
        (False, "E302 blank lines"),
    ]
    recorder.verdicts = [rejecting("rename it")]

    def down(prompt: str, **kwargs: Any) -> str:
        if step_of(prompt) != "fix_checks" or "claude:fix_checks" not in recorder.events:
            return recorder.claude(prompt, **kwargs)
        raise overloaded(503)

    build_once(tmp_path, monkeypatch, store, recorder=recorder, run=down)

    stored = store.get(UNIT)
    assert (stored.state, stored.cause, stored.step) == (
        PLANNED,
        "service_unavailable",
        "fix_checks",
    )
    assert stored.service_attempts == 1
    thread = thread_state(tmp_path)
    assert (thread.fix_rounds, thread.review_round, len(thread.review_rounds)) == (1, 1, 1)
    assert outcomes == ["interrupted"], "not recorded as a failed run"


def test_the_attempt_after_the_cap_fails_the_unit_with_its_text_and_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    for expected in (1, 2, 3):
        park_once(tmp_path, monkeypatch, store, overloaded())
        parked = store.get(UNIT)
        assert (parked.state, parked.cause) == (PLANNED, "service_unavailable")
        assert parked.service_attempts == expected

    park_once(tmp_path, monkeypatch, store, overloaded())

    failed = store.get(UNIT)
    assert (failed.state, failed.cause, failed.step) == (FAILED, "failed", "tests")
    assert "overloaded_error" in failed.note


def test_a_completed_step_ends_the_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    for _ in range(2):
        park_once(tmp_path, monkeypatch, store, overloaded())
    assert store.get(UNIT).service_attempts == 2
    recorder = Recorder(store)
    recorder.unit_test_results = [(False, "E501 line too long")]

    def down_in_the_fix(prompt: str, **kwargs: Any) -> str:
        if step_of(prompt) == "fix_checks":
            raise overloaded()
        return recorder.claude(prompt, **kwargs)

    build_once(tmp_path, monkeypatch, store, recorder=recorder, config=CAP, run=down_in_the_fix)

    stored = store.get(UNIT)
    assert (stored.state, stored.step) == (PLANNED, "fix_checks")
    assert stored.service_attempts == 1, "the implement step completed first"


def test_a_move_to_review_ends_the_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    for _ in range(2):
        park_once(tmp_path, monkeypatch, store, overloaded())

    build_once(tmp_path, monkeypatch, store, config=CAP)

    stored = store.get(UNIT)
    assert stored.state == IN_REVIEW
    assert stored.service_attempts == 0


def test_a_parking_by_the_probe_is_neither_counted_nor_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    probe.answer = Reachability(api=False, control=True)
    store = fresh_store(tmp_path)
    for _ in range(4):
        park_once(tmp_path, monkeypatch, store, outage("weak"))
        parked = store.get(UNIT)
        assert (parked.state, parked.cause) == (PLANNED, "service_unavailable")
        assert parked.service_attempts == 0

    park_once(tmp_path, monkeypatch, store, overloaded())

    assert store.get(UNIT).service_attempts == 1
    assert store.get(UNIT).state == PLANNED
