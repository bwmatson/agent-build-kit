"""A change is reviewed by a model once per plan, and its findings hold it (spec: plan-review).

A tick runs over a planning repo in a temporary folder with a fake model client; what a tick
started is what the shared builder saw.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import plan_review, shell, spans
from agent_build_kit.pipeline.plan_review import QUESTIONS, REVIEW_TOOLS
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, UnitState
from agent_build_kit.runtimes import AgentRateLimited
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
    GatedRuntime,
    Review,
    change_of,
    question_of,
    reply,
    run_bounded,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Review:
    return Review(tmp_path, monkeypatch)


@pytest.fixture
def one_call_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Review:
    """A review at the bound of one: review order is read from the order calls start."""
    return Review(tmp_path, monkeypatch, concurrency=1)


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
    ordered = review.passes_in_question_order
    for number, (asked, question) in enumerate(zip(ordered, QUESTIONS, strict=True), 1):
        assert f"{number}. {question}" in asked.prompt
        assert [other for other in QUESTIONS if other != question and other in asked.prompt] == []
        assert asked.allowed_tools == REVIEW_TOOLS
        assert "never needs a `Needs:` line on a group of its own change" in asked.prompt
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
    repaired = False

    def respond(request) -> str:
        nonlocal repaired
        if request.prompt.startswith("The plan of the change"):
            repaired = True
            return f"<<<TASKS\n{REPAIRED_TASKS}\nTASKS>>>"
        return reply() if repaired else reply(FIXABLE)

    review.runtime.respond = respond

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

    def respond(request) -> str:
        if request.prompt.startswith("The plan of the change"):
            n = next(rounds)
            return f"<<<TASKS\n{REPAIRED_TASKS}\n- [ ] 2.{n + 3} More.\nTASKS>>>"
        return reply(FIXABLE)

    review.runtime.respond = respond

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


def test_the_request_lists_the_units_in_build_order_with_merged_ones_and_their_pull_requests(
    tmp_path: Path,
) -> None:
    def unit(number: int, *, after: tuple[str, ...] = (), **more: object) -> StoredUnit:
        return StoredUnit.model_validate(
            {
                "id": f"{CHANGE}/{number}",
                "change": CHANGE,
                "title": f"Group {number}",
                "repo": "app",
                "tier": "unit-test",
                "depends_on": after,
                "estimated_lines": 100,
                "groups": (number,),
                **more,
            }
        )

    first = unit(1, state=MERGED, pr=11)
    second = unit(3, after=(first.id,), state=IN_REVIEW, pr=12)
    # Stored before the units it is built after, as a planner's listing may have it.
    last = unit(17, after=(second.id,))
    retired = unit(5, state=UnitState.RETIRED)
    other = unit(2).model_copy(update={"id": "other/2", "change": "other"})
    (tmp_path / "tasks.md").write_text(TASKS)

    ordered = plan_review.build_order([last, retired, other, second, first], CHANGE)
    prompt = plan_review.build_prompt(CHANGE, tmp_path, ordered, [])

    assert [u.id for u in ordered] == [first.id, second.id, last.id], (
        "the change's own units, merged ones kept, each after what it depends on; a retired unit "
        "and another change's unit are left out"
    )
    lines = [line for line in prompt.splitlines() if line.startswith(f"- {CHANGE}/")]
    assert lines == [
        f"- {CHANGE}/1 [app, unit-test] ({CHANGE} group 1) merged, pull request 11: Group 1",
        f"- {CHANGE}/3 [app, unit-test] ({CHANGE} group 3) in_review, pull request 12: Group 3",
        f"- {CHANGE}/17 [app, unit-test] ({CHANGE} group 17) planned: Group 17",
    ]
    assert "in the order they are built" in prompt


def test_changes_are_reviewed_by_the_most_urgent_priority_of_their_open_units(
    one_call_review: Review,
) -> None:
    review = one_call_review
    review.finish_default_change()
    review.add_change("alpha", 3, 3)
    review.add_change("zeta", 1)
    review.add_change("mid", 4, 2)

    review.tick()

    assert review.reviewed_order == ["zeta", "mid", "alpha"]


def test_changes_of_equal_urgency_are_reviewed_in_name_order(one_call_review: Review) -> None:
    review = one_call_review
    review.finish_default_change()
    review.add_change("b", 3)
    review.add_change("a", 3)
    review.add_change("c", 1)

    review.tick()

    assert review.reviewed_order == ["c", "a", "b"]


def test_a_change_ranks_by_its_open_units_not_by_one_that_has_merged(
    one_call_review: Review,
) -> None:
    review = one_call_review
    review.finish_default_change()
    review.add_change("late", 1, 4)
    review.add_change("other", 3)
    review.builder.store.set_state("late/1", MERGED)

    review.tick()

    assert review.reviewed_order == ["other", "late"], (
        "late's priority-1 unit has merged, so only its priority-4 unit counts"
    )


def test_a_promoted_units_stored_priority_counts_in_the_order(one_call_review: Review) -> None:
    review = one_call_review
    review.finish_default_change()
    review.add_change("aaa", 3)
    review.add_change("zzz", 4)
    review.builder.store.set_priority("zzz/1", 2)

    review.tick()

    assert review.reviewed_order == ["zzz", "aaa"]


def test_the_four_passes_of_a_review_are_in_flight_together_and_recorded_in_question_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = {number: threading.Event() for number in range(1, len(QUESTIONS) + 1)}

    def respond(request) -> str:
        number = question_of(request)
        if number < len(QUESTIONS):
            done[number + 1].wait(5)  # a later question answers first
        found = {"group": 1, "question": number, "kind": "advice", "evidence": f"pass {number}"}
        done[number].set()
        return reply(found)

    runtime = GatedRuntime(hold_until=len(QUESTIONS), respond=respond)
    review = Review(tmp_path, monkeypatch, concurrency=len(QUESTIONS), runtime=runtime)

    review.tick()

    assert runtime.most_in_flight == len(QUESTIONS)
    findings = plan_review.read_reviews(plan_review.record_path(review.inst))[CHANGE].findings
    assert [found.evidence for found in findings] == [
        f"pass {number}" for number in range(1, len(QUESTIONS) + 1)
    ]


def test_changes_reviewed_two_calls_at_a_time_leave_the_record_and_log_of_one_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    together = run_bounded(tmp_path / "two", monkeypatch, capsys, 2)
    alone = run_bounded(tmp_path / "one", monkeypatch, capsys, 1)

    assert together.most_in_flight == 2, "never more than two in flight, and two at some point"
    assert together.record == alone.record
    assert alone.log, "the single-call run logged the held changes"
    assert together.log == alone.log


def test_with_the_bound_at_one_calls_go_one_at_a_time_most_urgent_change_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    alone = run_bounded(tmp_path / "one", monkeypatch, capsys, 1)
    wider = run_bounded(tmp_path / "two", monkeypatch, capsys, 2)

    assert wider.most_in_flight > alone.most_in_flight, "the bound is what keeps calls apart"
    assert alone.most_in_flight == 1
    assert alone.started == tuple(
        (change, number)
        for change in ("zeta", "mid", "alpha")
        for number in range(1, len(QUESTIONS) + 1)
    )


def test_repairs_of_two_changes_run_one_at_a_time_and_both_changes_are_reviewed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repaired: set[str] = set()

    def respond(request) -> str:
        change = change_of(request)
        if request.prompt.startswith("The plan of the change"):
            repaired.add(change)
            return f"<<<TASKS\n{REPAIRED_TASKS}\nTASKS>>>"
        return reply() if change in repaired else reply(FIXABLE)

    runtime = GatedRuntime(hold_until=2, hold_repairs_until=2, repair_deadline=0.2, respond=respond)
    review = Review(tmp_path, monkeypatch, concurrency=4, runtime=runtime)
    review.finish_default_change()
    review.add_change("one", 3)
    review.add_change("two", 3)
    review.commit_planning()

    review.tick()

    assert runtime.most_in_flight >= 2, "the changes are reviewed together, only repairs are not"
    assert runtime.most_repairs_in_flight == 1
    subjects = shell.git(review.inst.root, "log", "--format=%s").stdout
    for change in ("one", "two"):
        assert f"plan({change}): repair the plan review's findings on group 2" in subjects
    assert review.asked == 4, "each repaired change is reviewed again"
    assert plan_review.held_changes(review.inst) == {}


def test_a_refused_call_starts_no_more_calls_and_lets_those_in_flight_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request) -> Exception | None:
        refused = change_of(request) == "urgent" and question_of(request) == 2
        return AgentRateLimited("usage window exhausted") if refused else None

    runtime = GatedRuntime(hold_until=len(QUESTIONS), refuse=refuse, respond=lambda _: reply())
    review = Review(tmp_path, monkeypatch, concurrency=len(QUESTIONS), runtime=runtime)
    review.finish_default_change()
    review.add_change("urgent", 1)
    review.add_change("later", 3)
    capsys.readouterr()

    review.tick()

    out = capsys.readouterr()
    assert runtime.most_in_flight == len(QUESTIONS)
    assert {change_of(r) for r in runtime.requests} == {"urgent"}, (
        "no call starts after the refusal"
    )
    assert sorted(question_of(r) for r in runtime.completed) == [1, 3, 4]
    assert plan_review.read_reviews(plan_review.record_path(review.inst)) == {}
    assert "reviewing plans failed" in out.out + out.err
    assert "AgentRateLimited" in out.out + out.err
