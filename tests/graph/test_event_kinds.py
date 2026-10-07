"""An event's kind and a feedback's source are fields, and the graph decides from them.

The text of a reason or of saved feedback is for people. Each test here changes the
text and leaves the field alone, or the reverse, and shows only the field matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import (
    FeedbackSource,
    RequeueReason,
    ReworkKind,
)
from tests.factories import unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

UNIT = unit().id
STALE = "a failure from the last attempt"


def waiting_in_review(tmp_path: Path) -> Recorder:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    return recorder


def test_the_requeue_reasons_are_the_fixed_set() -> None:
    assert {reason.value for reason in RequeueReason} == {
        "restart",
        "released",
        "resume",
        "from_failure",
        "parent_merged",
    }


def test_the_rework_kinds_are_the_fixed_set() -> None:
    assert {kind.value for kind in ReworkKind} == {
        "failing_checks",
        "conflict",
        "label",
        "changes_requested",
        "comment",
    }


def test_a_restart_throws_away_the_saved_failure_whatever_its_text_says(tmp_path: Path) -> None:
    recorder = waiting_in_review(tmp_path)
    recorder.store.set_feedback(UNIT, STALE)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(
            kind=EventKind.REQUEUE, requeue=RequeueReason.RESTART, reason="starting afresh"
        ),
    )

    assert recorder.store.get(UNIT).feedback == ""


@pytest.mark.parametrize(
    "requeue",
    [
        RequeueReason.RELEASED,
        RequeueReason.RESUME,
        RequeueReason.FROM_FAILURE,
        RequeueReason.PARENT_MERGED,
    ],
)
def test_every_other_requeue_keeps_the_saved_failure_even_when_its_text_says_restart(
    tmp_path: Path, requeue: RequeueReason
) -> None:
    recorder = waiting_in_review(tmp_path)
    recorder.store.set_feedback(UNIT, STALE)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REQUEUE, requeue=requeue, reason="restart"),
    )

    assert recorder.store.get(UNIT).feedback == STALE


@pytest.mark.parametrize("source", [FeedbackSource.TIER1, FeedbackSource.TIER2])
def test_feedback_from_the_checks_gets_the_fix_the_checks_prompt_by_its_source(
    tmp_path: Path, source: FeedbackSource
) -> None:
    recorder = waiting_in_review(tmp_path)
    ran = len(recorder.events)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(
            kind=EventKind.REWORK,
            rework=ReworkKind.FAILING_CHECKS,
            reason="the checks",
            feedback="E501 line too long in src/app.py",
            feedback_source=source,
        ),
    )
    assert recorder.store.get(UNIT).feedback_source == source
    tick(tmp_path, recorder)

    assert "claude:fix_checks" in recorder.events[ran:]
    assert "claude:rework" not in recorder.events[ran:]


def test_a_person_s_words_that_begin_like_a_check_failure_are_review_feedback(
    tmp_path: Path,
) -> None:
    recorder = waiting_in_review(tmp_path)
    ran = len(recorder.events)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(
            kind=EventKind.REWORK,
            rework=ReworkKind.COMMENT,
            reason="new comment",
            feedback="tier 1 failed: you forgot the import, please add it",
            from_person=True,
            feedback_source=FeedbackSource.REVIEW,
        ),
    )
    assert recorder.store.get(UNIT).feedback_source == FeedbackSource.REVIEW
    tick(tmp_path, recorder)

    assert "claude:rework" in recorder.events[ran:]
    assert "claude:fix_checks" not in recorder.events[ran:]
