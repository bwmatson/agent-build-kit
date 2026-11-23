"""A change is reviewed by a model once per plan, and its findings hold it (spec: plan-review).

A tick runs over a planning repo in a temporary folder with a fake model client; what a tick
started is what the shared builder saw.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import plan_review, shell, spans
from agent_build_kit.pipeline.plan_review import QUESTIONS, REVIEW_TOOLS
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import MERGED, PLANNED
from tests.plan_review_support import (
    ADVICE,
    CHANGE,
    DESIGN,
    EDITED_TASKS,
    FINDING,
    FIXABLE,
    PROPOSAL,
    REPAIRED_TASKS,
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


def test_a_finding_does_not_hold_a_unit_that_has_started(review: Review) -> None:
    review.tick()
    [first, *_] = review.builder.started
    review.runtime.answer = reply(FINDING)
    review.edit_tasks(EDITED_TASKS)
    review.builder.store.set_state(
        first, PLANNED, note="rework requested: a check failed", cause=Cause.REWORK
    )
    assert not review.builder.store.get(first).unstarted, "the unit ran: it has work to keep"
    before = review.builder.started.count(first)

    review.tick()

    assert CHANGE in plan_review.held_changes(review.inst)
    assert review.builder.started.count(first) == before + 1, (
        "the review holds only units that have not started; this one is built again"
    )


def test_each_question_is_asked_in_its_own_pass_with_read_only_tools_over_the_repos(
    review: Review,
) -> None:
    review.tick()

    assert len(review.passes) == len(QUESTIONS)
    for number, (asked, question) in enumerate(zip(review.passes, QUESTIONS, strict=True), 1):
        assert f"{number}. {question}" in asked.prompt
        assert [other for other in QUESTIONS if other != question and other in asked.prompt] == []
        assert asked.allowed_tools == REVIEW_TOOLS
        assert asked.permission_mode == "allowed_tools_only"
        assert review.inst.repo("app").path in [str(path) for path in asked.add_dirs] or not (
            Path(review.inst.repo("app").path).is_dir()
        )


def test_advice_is_recorded_and_shown_but_holds_nothing(review: Review) -> None:
    review.runtime.answer = reply(ADVICE)

    review.tick()

    assert review.builder.started, "advice never holds a unit"
    recorded = plan_review.read_reviews(plan_review.record_path(review.inst))[CHANGE]
    assert [found.kind for found in recorded.findings] == ["advice"]
    assert CHANGE not in plan_review.held_changes(review.inst)


def test_a_cleared_finding_is_not_raised_again_while_its_group_text_stands(
    review: Review,
) -> None:
    review.runtime.answer = reply(FINDING)
    review.tick()
    assert plan_review.clear(review.inst, CHANGE, "renamed on purpose") == 1

    review.edit_tasks(TASKS + "\n## 3. [app] [unit-test] Third group\n\n- [ ] 3.1 Test: it.\n")
    review.tick()

    assert review.asked == 2, "the edit is a new plan, and a fresh review"
    assert CHANGE not in plan_review.held_changes(review.inst), (
        "the model found the cleared point again on group 2, whose text did not change"
    )


def test_a_cleared_finding_holds_again_once_its_group_is_edited(review: Review) -> None:
    review.runtime.answer = reply(FINDING)
    review.tick()
    plan_review.clear(review.inst, CHANGE, "renamed on purpose")

    review.edit_tasks(TASKS.replace("asserts it again.", "asserts it once more."))
    review.tick()

    assert CHANGE in plan_review.held_changes(review.inst), (
        "group 2 changed, so the clear no longer covers what the reviewer found there"
    )


def test_a_blocker_with_a_fix_is_repaired_committed_and_reviewed_again(review: Review) -> None:
    review.commit_planning()
    review.repair_with(REPAIRED_TASKS, review_answer=reply(FIXABLE))
    answers = iter([reply(FIXABLE)] * len(QUESTIONS) + [reply()] * len(QUESTIONS))

    def act(request) -> None:
        if request.prompt.startswith("The plan of the change"):
            review.runtime.answer = f"<<<TASKS\n{REPAIRED_TASKS}\nTASKS>>>"
        else:
            review.runtime.answer = next(answers)

    review.runtime.act = act

    review.tick()

    assert len(review.repairs) == 1
    assert review.tasks == REPAIRED_TASKS
    log = shell.git(review.inst.root, "log", "--format=%s", "-1").stdout
    assert log.startswith(f"plan({CHANGE}): repair the plan review's findings on group 2")
    assert review.asked == 2, "the repaired plan is reviewed again in the same round"
    assert CHANGE not in plan_review.held_changes(review.inst)
    assert review.builder.started


def test_a_repair_that_changes_a_group_heading_is_refused_and_the_change_holds(
    review: Review,
) -> None:
    review.commit_planning()
    review.repair_with(
        REPAIRED_TASKS.replace("Second group", "Renamed group"), review_answer=reply(FIXABLE)
    )

    review.tick()

    assert len(review.repairs) == 1
    assert review.tasks == TASKS, "the refused repair is not written"
    assert CHANGE in plan_review.held_changes(review.inst)
    assert review.builder.started == [] or f"{CHANGE}/1" not in review.builder.started


def test_a_repair_leaves_a_tasks_md_with_edits_that_are_not_committed(review: Review) -> None:
    review.commit_planning()
    review.edit_tasks(TASKS + "\nA person is editing this.\n")
    review.repair_with(REPAIRED_TASKS, review_answer=reply(FIXABLE))

    review.tick()

    assert review.repairs == [], "the person's edit is not overwritten"
    assert CHANGE in plan_review.held_changes(review.inst)


def test_repairs_stop_at_the_configured_count(review: Review) -> None:
    review.commit_planning()
    review.repair_with(REPAIRED_TASKS, review_answer=reply(FIXABLE))
    rounds = iter(range(100))

    def act(request) -> None:
        if request.prompt.startswith("The plan of the change"):
            n = next(rounds)
            review.runtime.answer = f"<<<TASKS\n{REPAIRED_TASKS}\n- [ ] 2.{n + 3} More.\nTASKS>>>"
        else:
            review.runtime.answer = reply(FIXABLE)

    review.runtime.act = act

    review.tick()

    assert len(review.repairs) == review.inst.config.planning.plan_review_repairs
    assert CHANGE in plan_review.held_changes(review.inst), "what repair could not fix holds"


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


def test_a_clear_stands_when_a_unit_lands_and_its_boxes_are_ticked(review: Review) -> None:
    review.runtime.answer = reply(FINDING)
    review.tick()
    assert plan_review.clear(review.inst, CHANGE, "accepted") == 1

    review.builder.store.set_state(f"{CHANGE}/1", MERGED)
    review.edit_tasks(TASKS.replace("- [ ] 1.", "- [x] 1."))
    review.tick()

    assert review.asked == 1, "a unit landing and its boxes ticking is progress, not an edit"
    assert CHANGE not in plan_review.held_changes(review.inst)
    recorded = plan_review.read_reviews(plan_review.record_path(review.inst))[CHANGE]
    assert recorded.note == "accepted"


def test_a_review_that_times_out_is_not_asked_again_on_the_next_tick(review: Review) -> None:
    review.runtime.ok = False
    review.runtime.error = "timed out after 600 seconds"
    review.runtime.answer = ""

    review.tick()
    started = len(review.builder.started)
    review.tick()

    assert review.asked == 1, "the failed plan is asked again only after the retry interval"
    assert started, "the unit starts on the first tick"
    assert len(review.builder.started) >= started


def test_a_failed_review_is_asked_again_once_the_retry_interval_has_passed(
    review: Review, monkeypatch: pytest.MonkeyPatch
) -> None:
    review.runtime.ok = False
    review.runtime.error = "timed out"
    review.runtime.answer = ""
    review.tick()
    later = spans.clock.now() + plan_review.RETRY_AFTER + timedelta(minutes=1)
    monkeypatch.setattr(spans.clock, "now", lambda: later)

    review.tick()

    assert review.asked == 2


def test_the_request_carries_the_files_the_tasks_name_at_the_default_branch(
    review: Review,
) -> None:
    checkout = review.inst.repo("app").path
    (checkout / "tests").mkdir(parents=True)
    (checkout / "tests" / "test_shared.py").write_text("SHARED-MARKER = 1\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("add", "."),
        ("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed"),
    ):
        shell.git(checkout, *args)

    review.tick()

    assert "SHARED-MARKER" in review.prompt
