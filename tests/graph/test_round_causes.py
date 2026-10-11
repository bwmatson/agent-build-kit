"""A review round's span names why the round ran (spec: unit-timeline-is-recorded).

Each test drives the real graph: a verdict, a delivered rework event or a restack that
could not be merged sends the unit back, the round runs, and the ledger's span for the
round carries its cause.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.fake_clock import span_lines
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import RETIRED, Adapting, decisions, reviewers
from tests.graph_driver import fresh, tick


def causes(workspace: Installation, node: str) -> list[str]:
    return [s["cause"] for s in span_lines(workspace) if s["node"] == node and not s["waited"]]


def test_a_rework_after_a_review_that_asked_for_changes_has_the_cause_review(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [json.dumps({"approved": False, "feedback": "rename the lock"})]

    tick(tmp_path, recorder)

    assert causes(workspace, "rework") == ["review"]


@pytest.mark.parametrize(
    ("source", "cause"),
    [
        (FeedbackSource.REVIEW, "review"),
        (FeedbackSource.CI, "check"),
        (FeedbackSource.CONFLICT, "conflict"),
    ],
)
def test_a_rework_sent_back_by_an_event_has_the_cause_of_what_sent_it(
    tmp_path: Path, workspace: Installation, source: FeedbackSource, cause: str
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    event = ResumeEvent(
        kind=EventKind.REWORK, reason="sent back", feedback="fix it", feedback_source=source
    )
    tick(tmp_path, recorder, event=event)

    tick(tmp_path, recorder)

    assert causes(workspace, "rework") == [cause]


def test_an_adapt_that_a_restack_started_has_the_cause_conflict(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    _who, review = reviewers(recorder)
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""), ("test_console", "retire", RETIRED))],
        old_tests=("test_click", "test_console"),
        present={"test_click"},
    )

    build(tmp_path, recorder, base="spec/c/2", **adapting.overrides(), **review)

    assert causes(workspace, "adapt") == ["conflict"]


def test_a_node_that_is_not_a_round_has_no_cause(tmp_path: Path, workspace: Installation) -> None:
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder)

    assert {s["cause"] for s in span_lines(workspace) if s["node"] == "implement"} == {""}
