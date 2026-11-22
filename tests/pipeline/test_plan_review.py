"""A change is reviewed by a model once per plan, and its findings hold it (spec: plan-review).

A tick runs over a planning repo in a temporary folder with a fake model client; what a tick
started is what the shared builder saw.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.plan_review import QUESTIONS
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.plan_review_support import (
    CHANGE,
    DESIGN,
    EDITED_TASKS,
    FINDING,
    PROPOSAL,
    SPEC,
    TASKS,
    Review,
    reply,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Review:
    return Review(tmp_path, monkeypatch)


def test_a_change_with_planned_units_and_no_review_is_reviewed_once(review: Review) -> None:
    assert review.tick() == 0
    assert review.tick() == 0

    assert review.asked == 1, "the second tick finds a review of the same plan and asks nothing"
    assert review.builder.started, "no finding: the first unit starts"


def test_the_request_holds_the_questions_the_artifacts_the_units_and_the_mechanical_report(
    review: Review,
) -> None:
    review.tick()

    assert review.asked == 1, "the change is reviewed, so a request exists to read"
    prompt = review.prompt
    assert len(QUESTIONS) == 4
    for question in QUESTIONS:
        assert question in prompt
    for artifact in (PROPOSAL, DESIGN, SPEC, TASKS):
        assert artifact in prompt
    for unit_id in (f"{CHANGE}/1", f"{CHANGE}/2"):
        assert unit_id in prompt
    assert "`tests/test_shared.py` is named by groups 1 and 2" in prompt, (
        "the report `abk tags` prints for the change, so the model need not repeat it"
    )


def test_an_edit_of_tasks_md_asks_once_more_and_leaves_a_started_unit_alone(
    review: Review,
) -> None:
    review.tick()
    assert review.asked == 1
    started = list(review.builder.started)

    review.edit_tasks(EDITED_TASKS)
    review.tick()
    review.tick()

    assert review.asked == 2, "a new hash is a new review, and then no more"
    assert review.builder.started[: len(started)] == started
    assert review.builder.finished[: len(started)] == started, (
        "the started unit was not interrupted"
    )


def test_a_finding_holds_the_change_so_no_unit_starts(review: Review) -> None:
    review.runtime.answer = reply(FINDING)

    assert review.tick() == 0
    review.tick()

    assert review.builder.started == []
    assert review.asked == 1, "a held change is not reviewed again while its plan is unchanged"


def test_a_finding_holds_the_next_start_of_a_unit_sent_back_for_rework(
    review: Review,
) -> None:
    review.tick()
    [first, *_] = review.builder.started
    review.runtime.answer = reply(FINDING)
    review.edit_tasks(EDITED_TASKS)
    review.builder.store.set_state(
        first, PLANNED, note="rework requested: a check failed", cause=Cause.REWORK
    )
    before = len(review.builder.started)

    review.tick()

    assert len(review.builder.started) == before, "the held change starts nothing, rework included"


@pytest.mark.parametrize(
    ("ok", "error", "answer", "why"),
    [
        (False, "timed out after 600 seconds", "", "timed out after 600 seconds"),
        (True, "", "I think the plan is probably fine, no JSON here.", "could not be read"),
    ],
    ids=["the client times out", "the answer is unreadable"],
)
def test_a_review_that_fails_holds_nothing_and_the_log_says_why(
    review: Review,
    capsys: pytest.CaptureFixture[str],
    ok: bool,
    error: str,
    answer: str,
    why: str,
) -> None:
    review.runtime.ok, review.runtime.error, review.runtime.answer = ok, error, answer
    capsys.readouterr()

    assert review.tick() == 0

    out = capsys.readouterr()
    assert review.builder.started, "the unit starts: a failed review never stops the pipeline"
    assert "plan review" in out.out + out.err
    assert why in out.out + out.err


def test_with_review_plans_off_no_client_is_asked_and_the_unit_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = Review(tmp_path / "on", monkeypatch)
    on.runtime.answer = reply(FINDING)
    assert on.tick() == 0
    assert on.builder.started == [], "with the setting on, the same finding holds the change"

    off = Review(tmp_path / "off", monkeypatch, review_plans=False)
    off.runtime.answer = reply(FINDING)

    assert off.tick() == 0

    assert off.asked == 0
    assert off.builder.started
