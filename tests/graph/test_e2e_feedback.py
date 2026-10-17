"""The feedback saved on a e2e-test failure holds the unit's own failures and names the
pre-existing ones once; no untouched test's output reaches the agent (spec: e2e-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.e2e_wait_fakes import (
    BROKEN,
    OLD,
    OLD_OUTPUT,
    OWN,
    OWN_OUTPUT,
    Failing,
    Told,
    snapshot_of,
    verdict_of,
)
from tests.graph_driver import fresh, tick

PERSON = "please rename the helper"
TAIL = f"{OWN_OUTPUT}\n{OLD_OUTPUT}\n"


def failed_run(
    tmp_path: Path,
    *,
    feedback: str = "",
    verdict=None,
    tail: str = TAIL,
    tests: tuple[str, ...] = (),
):
    """A e2e-test that failed `tests` with `verdict` and `tail` as its output; the unit's
    stored feedback and its source afterwards."""
    recorder = fresh(tmp_path)
    if feedback:
        recorder.store.set_feedback("add-marker/1", feedback, source=FeedbackSource.REVIEW)
    e2e = Failing(recorder.events, snapshot_of(*tests, tail=tail), verdict)
    tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        run_e2e=e2e.run,
        e2e_verdict=e2e.judged,
        on_preexisting=Told(),
    )
    stored = recorder.store.get("add-marker/1")
    return stored.feedback, stored.feedback_source, e2e


def test_a_mixed_failure_saves_the_units_own_failure_line_and_names_the_pre_existing_test_once(
    tmp_path: Path,
) -> None:
    feedback, source, _ = failed_run(
        tmp_path, verdict=verdict_of(own=(OWN,), old=(OLD,)), tests=(OWN, OLD)
    )

    assert feedback.startswith("e2e-test failed:\n## e2e-test results")
    assert OWN in feedback, "the unit's own failure is listed"
    assert "assert in test_own" in feedback
    assert feedback.count(OLD) == 1, "named once"
    assert "also failing on the base, recorded: " + OLD in feedback
    assert "assert in test_old" not in feedback, "its failure line is not given to the agent"
    assert OLD_OUTPUT not in feedback, "nor is any of the output that holds its block"
    assert source is FeedbackSource.E2E


def test_a_failure_broken_by_the_unit_is_kept_as_the_units_own(tmp_path: Path) -> None:
    feedback, _, _ = failed_run(
        tmp_path, verdict=verdict_of(broken=(BROKEN,), old=(OLD,)), tests=(BROKEN, OLD)
    )

    assert BROKEN in feedback and "assert in test_broken" in feedback
    assert OLD_OUTPUT not in feedback
    assert feedback.count(OLD) == 1


def test_the_tail_is_kept_when_every_failed_test_in_it_is_the_units(tmp_path: Path) -> None:
    feedback, _, e2e = failed_run(
        tmp_path, verdict=verdict_of(own=(OWN,)), tests=(OWN,), tail=OWN_OUTPUT
    )

    assert e2e.asked == 1, "the failures were classified, and none is untouched"
    assert OWN_OUTPUT in feedback
    assert "also failing on the base" not in feedback


def test_an_unclassified_failure_saves_the_text_saved_today(tmp_path: Path) -> None:
    feedback, source, e2e = failed_run(tmp_path, verdict=None, tests=(OWN, OLD))

    assert feedback == ("e2e-test failed:\n" + e2e.snapshot).strip()
    assert e2e.asked == 1, "the node asked, and was told nothing was classified"
    assert source is FeedbackSource.E2E


def test_a_persons_own_words_stay_and_no_untouched_output_is_added_to_them(
    tmp_path: Path,
) -> None:
    feedback, source, _ = failed_run(
        tmp_path,
        feedback=PERSON,
        verdict=verdict_of(own=(OWN,), old=(OLD,)),
        tests=(OWN, OLD),
    )

    assert feedback.startswith(PERSON + "\n\ne2e-test failed:\n")
    assert OWN in feedback and feedback.count(OLD) == 1
    assert OLD_OUTPUT not in feedback and "assert in test_old" not in feedback
    assert source is FeedbackSource.REVIEW, "still the person's, as for any e2e-test failure"


def test_the_prompt_made_from_the_saved_text_holds_none_of_an_untouched_tests_output(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    e2e = Failing(
        recorder.events, snapshot_of(OWN, OLD, tail=TAIL), verdict_of(own=(OWN,), old=(OLD,))
    )
    overrides = dict(
        tier="e2e-test",
        run_e2e=e2e.run,
        e2e_verdict=e2e.judged,
        on_preexisting=Told(),
    )
    tick(tmp_path, recorder, **overrides)
    sent = len(recorder.prompts)

    requeue = ResumeEvent(
        kind=EventKind.REQUEUE, requeue=RequeueReason.FROM_FAILURE, reason="try again"
    )
    tick(tmp_path, recorder, event=requeue, **overrides)
    tick(tmp_path, recorder, **overrides)

    prompts = recorder.prompts[sent:]
    fixing = [p for p in prompts if OWN in p]
    assert fixing, "a prompt was made from the saved failure"
    for prompt in fixing:
        assert OLD_OUTPUT not in prompt and "assert in test_old" not in prompt
