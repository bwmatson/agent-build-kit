"""The feedback saved on a tier 2 failure holds the unit's own failures and names the
pre-existing ones once; no untouched test's output reaches the agent (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.graph_driver import fresh, tick
from tests.tier2_wait_fakes import (
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
    """A tier 2 that failed `tests` with `verdict` and `tail` as its output; the unit's
    stored feedback and its source afterwards."""
    recorder = fresh(tmp_path)
    if feedback:
        recorder.store.set_feedback("add-marker/1", feedback, source=FeedbackSource.REVIEW)
    tier2 = Failing(recorder.events, snapshot_of(*tests, tail=tail), verdict)
    tick(
        tmp_path,
        recorder,
        tier="tier2",
        run_tier2=tier2.run,
        tier2_verdict=tier2.judged,
        on_preexisting=Told(),
    )
    stored = recorder.store.get("add-marker/1")
    return stored.feedback, stored.feedback_source, tier2


def test_a_mixed_failure_saves_the_units_own_output_and_names_the_pre_existing_test_once(
    tmp_path: Path,
) -> None:
    feedback, source, _ = failed_run(
        tmp_path, verdict=verdict_of(own=(OWN,), old=(OLD,)), tests=(OWN, OLD)
    )

    assert feedback.startswith("tier 2 failed:\n## Tier 2 results")
    assert OWN in feedback, "the unit's own failure is listed"
    assert "assert in test_own" in feedback
    assert feedback.count(OLD) == 1, "named once"
    assert "also failing on the base, recorded: " + OLD in feedback
    assert "assert in test_old" not in feedback, "its failure line is not given to the agent"
    assert OLD_OUTPUT not in feedback, "nor is any of the output that holds its block"
    assert source is FeedbackSource.TIER2


def test_a_failure_broken_by_the_unit_is_kept_as_the_units_own(tmp_path: Path) -> None:
    feedback, _, _ = failed_run(
        tmp_path, verdict=verdict_of(broken=(BROKEN,), old=(OLD,)), tests=(BROKEN, OLD)
    )

    assert BROKEN in feedback and "assert in test_broken" in feedback
    assert OLD_OUTPUT not in feedback
    assert feedback.count(OLD) == 1


def test_the_tail_is_kept_when_every_failed_test_in_it_is_the_units(tmp_path: Path) -> None:
    feedback, _, tier2 = failed_run(
        tmp_path, verdict=verdict_of(own=(OWN,)), tests=(OWN,), tail=OWN_OUTPUT
    )

    assert tier2.asked == 1, "the failures were classified, and none is untouched"
    assert OWN_OUTPUT in feedback
    assert "also failing on the base" not in feedback


def test_an_unclassified_failure_saves_the_text_saved_today(tmp_path: Path) -> None:
    feedback, source, tier2 = failed_run(tmp_path, verdict=None, tests=(OWN, OLD))

    assert feedback == ("tier 2 failed:\n" + tier2.snapshot).strip()
    assert tier2.asked == 1, "the node asked, and was told nothing was classified"
    assert source is FeedbackSource.TIER2


def test_a_persons_own_words_stay_and_no_untouched_output_is_added_to_them(
    tmp_path: Path,
) -> None:
    feedback, source, _ = failed_run(
        tmp_path,
        feedback=PERSON,
        verdict=verdict_of(own=(OWN,), old=(OLD,)),
        tests=(OWN, OLD),
    )

    assert feedback.startswith(PERSON + "\n\ntier 2 failed:\n")
    assert OWN in feedback and feedback.count(OLD) == 1
    assert OLD_OUTPUT not in feedback and "assert in test_old" not in feedback
    assert source is FeedbackSource.REVIEW, "still the person's, as for any tier 2 failure"
