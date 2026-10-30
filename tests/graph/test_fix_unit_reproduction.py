"""A first build of a unit of a fix change checks that its test still fails before `tests` runs
(spec: fix-unit-reproduction).

The runner's `reproduce_test` is faked at the point it is bound, so these tests are about where
the graph sends the unit by each outcome, and for which units the check runs at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.fix_reproduction import Outcome, Reproduction
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import HELD, SATISFIED
from tests.conftest import make_installation
from tests.factories import stored_unit, unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

TEST = "tests/test_widget.py::test_renders_the_label"
CHANGE = "fix-test-tests-test-widget-py-test-renders-the-label"
NOT_REPRODUCED = "not reproduced: 0 of 5 runs alone, 0 of 5 under load"


def tasks_of(test: str) -> str:
    return (
        "# Tasks\n\n"
        f"## 1. [app] [unit-test] Make `{test}` deterministic\n\n"
        "- [ ] 1.1 Test: reproduce it\n- [ ] 1.2 Make it pass\n"
    )


class Asked:
    """A `reproduce_test` that answers `outcome` and keeps what it was asked."""

    def __init__(self, outcome: Outcome, note: str = "") -> None:
        self.outcome = outcome
        self.note = note
        self.calls: list[tuple[str, int]] = []

    def __call__(self, *, cwd: Path, test: str, runs: int) -> Reproduction:
        self.calls.append((test, runs))
        return Reproduction(outcome=self.outcome, note=self.note)


def fix_unit(
    tmp_path: Path, change: str = CHANGE, *, runs: int | None = None, text: str | None = None
) -> tuple[Installation, Recorder, Any]:
    limits = {} if runs is None else {"global_limits": {"fix_reproduction_runs": runs}}
    installation = make_installation(tmp_path, **limits)
    tasks = installation.changes_dir / change / "tasks.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_text(text if text is not None else tasks_of(TEST))
    recorder = fresh(tmp_path)
    uid = f"{change}/1"
    recorder.store.upsert([stored_unit(uid, change=change, groups=(1,))])
    return installation, recorder, unit(uid, change=change, groups=(1,))


def built(recorder: Recorder) -> bool:
    return "claude:tests" in recorder.events


def test_a_test_that_fails_goes_on_to_the_tests_step(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    answer = Asked(Outcome.FAILS)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == [(TEST, 5)], "the test the change is named for, the configured times"
    assert built(recorder)


def test_the_number_of_runs_is_the_setting(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path, runs=2)
    answer = Asked(Outcome.FAILS)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == [(TEST, 2)]


def test_a_test_that_never_fails_holds_the_unit_for_a_person(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    outcome = tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(subject.id)
    assert stored.state == HELD and stored.state != SATISFIED
    assert stored.cause is Cause.NEEDS_HUMAN
    assert NOT_REPRODUCED in stored.note
    assert not built(recorder), "nothing is built for a test that does not fail"


def test_a_restart_with_a_note_builds_the_held_unit_without_the_check(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)
    restart = ResumeEvent(
        kind=EventKind.REQUEUE,
        requeue=RequeueReason.RESTART,
        reason="restart",
        guidance="a rare race: build the fix anyway",
    )

    tick(tmp_path, recorder, subject=subject, event=restart, reproduce_test=answer)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert built(recorder)
    assert len(answer.calls) == 1, "the restarted build is not checked again"


def test_a_plain_requeue_after_the_hold_builds_without_the_check(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)
    requeue = ResumeEvent(
        kind=EventKind.REQUEUE, requeue=RequeueReason.FROM_FAILURE, reason="requeued"
    )

    tick(tmp_path, recorder, subject=subject, event=requeue, reproduce_test=answer)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert built(recorder)
    assert len(answer.calls) == 1


def test_a_skipped_check_builds_as_today(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)

    tick(tmp_path, recorder, subject=subject, reproduce_test=Asked(Outcome.SKIPPED))

    assert built(recorder)
    assert recorder.store.get(subject.id).state != HELD


def test_a_test_gone_from_the_tree_satisfies_the_unit_with_the_reason(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    why = f"{TEST} is no longer in the tree"

    outcome = tick(tmp_path, recorder, subject=subject, reproduce_test=Asked(Outcome.GONE, why))

    assert outcome.status == RunStatus.SATISFIED
    stored = recorder.store.get(subject.id)
    assert stored.state == SATISFIED
    assert why in stored.note
    assert not built(recorder)


def test_a_test_fixed_by_a_change_merged_since_satisfies_the_unit_naming_it(
    tmp_path: Path,
) -> None:
    installation, recorder, subject = fix_unit(tmp_path)
    fixed = fix_change_name(TEST, "fix-flaky")
    (installation.changes_dir / "archive" / f"2999-01-01-{fixed}").mkdir(parents=True)
    answer = Asked(Outcome.FAILS)

    outcome = tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert outcome.status == RunStatus.SATISFIED
    assert fixed in recorder.store.get(subject.id).note
    assert answer.calls == [], "nothing is run for a test already fixed"
    assert not built(recorder)


def test_zero_runs_skips_the_check(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path, runs=0)
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []
    assert built(recorder)


def test_a_unit_of_an_ordinary_change_is_not_checked(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path, "add-marker")
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []
    assert built(recorder)


def test_a_unit_of_a_product_defect_change_is_not_checked(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path, "fix-product-defect-widget-label")
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []
    assert built(recorder)


def test_a_rework_is_not_checked(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    recorder.made = 1  # the branch already holds work
    recorder.store.set_feedback(subject.id, "review asked for a change")
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []


def test_a_build_started_with_a_note_is_not_checked(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    recorder.store.set_guidance(subject.id, "build it anyway")
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []
    assert built(recorder)


def test_a_change_whose_test_cannot_be_read_builds_as_today(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path, text="# Tasks\n\n## 1. [app] [unit-test] Do it\n")
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == []
    assert built(recorder)
