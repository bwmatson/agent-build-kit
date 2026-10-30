"""A first build of a unit of a fix change checks that its test still fails before `tests` runs
(spec: fix-unit-reproduction).

The runner's `reproduce_test` is faked at the point it is bound, so these tests are about where
the graph sends the unit by each outcome, and for which units the check runs at all.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph import nodes
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.fix_reproduction import Outcome, Reproduction
from agent_build_kit.pipeline.flakes import Flake, fix_change_name, flake_record
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import HELD, SATISFIED
from tests.conftest import make_installation
from tests.factories import stored_unit, unit
from tests.graph.branch_fakes import prepared
from tests.graph.test_build_path import build as build_on_branch
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


def record_first_failure(installation: Installation, tmp_path: Path) -> Path:
    """The flake record holds the test's first failure, whose bundle is a folder on disk."""
    bundle = tmp_path / "state" / "test-failures" / "bundle-1"
    bundle.mkdir(parents=True)
    flake_record(installation).append(
        Flake(
            test=TEST,
            command="uv run pytest",
            output=f"FAILED {TEST} - assert 3 == 0 (a 3-second gap in ps start times)",
            at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            unit="other/1",
            evidence=str(bundle),
        )
    )
    return bundle


def prompts_of(recorder: Recorder) -> str:
    return "\n".join(recorder.prompts)


def test_a_test_that_never_fails_builds_with_guidance_and_is_not_held(tmp_path: Path) -> None:
    installation, recorder, subject = fix_unit(tmp_path)
    bundle = record_first_failure(installation, tmp_path)
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)

    outcome = tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert outcome.status != RunStatus.HELD
    stored = recorder.store.get(subject.id)
    assert stored.state not in (HELD, SATISFIED), "neither held nor satisfied by the check"
    assert built(recorder)
    text = prompts_of(recorder)
    assert NOT_REPRODUCED in text, "the counts"
    assert "a 3-second gap in ps start times" in text, "the first failure's output"
    assert str(bundle) in text, "the failing run's bundle"
    assert "whether the cause is already gone" in text
    assert "make no change" in text and "red-first" not in text


def test_the_findings_are_not_a_persons_request_and_are_cleared_after_the_build(
    tmp_path: Path,
) -> None:
    _, recorder, subject = fix_unit(tmp_path)

    tick(
        tmp_path,
        recorder,
        subject=subject,
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
    )

    builders = [p for p in recorder.prompts if NOT_REPRODUCED in p]
    assert len(builders) >= 2, "the tests and the implementation prompts carry it"
    assert all("A person asked for this" not in p for p in builders)
    reviews = "\n".join(recorder.contexts)
    assert NOT_REPRODUCED not in reviews and "reproduction check" not in reviews
    assert "A person asked" not in reviews
    assert recorder.store.get(subject.id).guidance == ""
    assert thread_state(tmp_path, subject.id).reproduction_guidance == ""


def thread_state(tmp_path: Path, unit_id: str) -> Any:
    async def go() -> Any:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return (await thread_position(saver, unit_id)).state

    return asyncio.run(go())


def test_the_tests_step_is_told_what_to_do_when_the_cause_is_gone(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)

    tick(
        tmp_path,
        recorder,
        subject=subject,
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
    )

    tests_prompt = next(p for p in recorder.prompts if "test tasks" in p)
    assert "write nothing" in tests_prompt and "state why" in tests_prompt


def test_the_bundle_is_left_out_when_there_is_none(tmp_path: Path) -> None:
    installation, recorder, subject = fix_unit(tmp_path)
    flake_record(installation).append(
        Flake(
            test=TEST,
            command="c",
            output="FAILED x - boom",
            at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            evidence=str(tmp_path / "not-there"),
        )
    )

    tick(
        tmp_path,
        recorder,
        subject=subject,
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
    )

    assert "boom" in prompts_of(recorder)
    assert "not-there" not in prompts_of(recorder)


def test_a_build_that_makes_a_change_is_built_as_a_fix(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)

    outcome = tick(
        tmp_path,
        recorder,
        subject=subject,
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
    )

    assert outcome.status != RunStatus.SATISFIED
    assert recorder.store.get(subject.id).state != SATISFIED
    assert "claude:impl" in recorder.events and recorder.made > 0
    assert NOT_REPRODUCED in prompts_of(recorder), "built with the check's findings"


def test_a_build_that_makes_no_change_and_says_why_is_satisfied_with_its_statement(
    tmp_path: Path,
) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    cause = "the race was removed by commit 4f2a9c1, which stopped stepping the clock"

    def say_why(prompt: str, **kwargs: Any) -> str:
        recorder.claude(prompt, **kwargs)
        return cause

    outcome = tick(
        tmp_path,
        recorder,
        subject=subject,
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
        run=say_why,
        commit=lambda message, **kwargs: 0,
    )

    assert outcome.status == RunStatus.SATISFIED
    stored = recorder.store.get(subject.id)
    assert stored.state == SATISFIED
    assert cause in stored.note
    assert NOT_REPRODUCED in stored.note


def test_a_requeue_after_the_check_does_not_repeat_it(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    recorder.unit_test_ok = False  # the first build does not finish, so its thread stays
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)
    requeue = ResumeEvent(
        kind=EventKind.REQUEUE, requeue=RequeueReason.FROM_FAILURE, reason="requeued"
    )

    tick(tmp_path, recorder, subject=subject, event=requeue, reproduce_test=answer)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert len(answer.calls) == 1


def test_a_restart_without_a_note_does_not_repeat_the_check(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)
    recorder.unit_test_ok = False
    answer = Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)
    restart = ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESTART, reason="again")

    tick(tmp_path, recorder, subject=subject, event=restart, reproduce_test=answer)
    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert len(answer.calls) == 1


def test_a_skipped_check_builds_as_today(tmp_path: Path) -> None:
    _, recorder, subject = fix_unit(tmp_path)

    tick(tmp_path, recorder, subject=subject, reproduce_test=Asked(Outcome.SKIPPED))

    assert built(recorder)
    assert recorder.store.get(subject.id).state != HELD
    assert "reproduction check" not in prompts_of(recorder)


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


def test_a_no_change_build_of_a_test_only_group_keeps_the_statement_and_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nodes, "is_fix_change", lambda change: True)
    cause = "the race was removed by commit 4f2a9c1"
    recorder, _ = prepared(
        tmp_path,
        groups={"add-marker": {1: (f"Make `{TEST}` deterministic", "")}},
        e2e=(1,),
        no_tests_for="1",
        tests_accounts={"1": cause},
    )

    outcome = build_on_branch(
        tmp_path,
        recorder,
        **recorder.overrides(tmp_path),
        reproduce_test=Asked(Outcome.NOT_REPRODUCED, NOT_REPRODUCED),
    )

    assert outcome.status == RunStatus.SATISFIED, outcome.detail
    note = recorder.store.get(unit().id).note
    assert cause in note and NOT_REPRODUCED in note
