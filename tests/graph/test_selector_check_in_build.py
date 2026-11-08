"""The build checks that the tests commit of an `[integration-test]` group carries the
`integration` selector: a commit whose tests lack it goes back to the tests step with the reason,
one whose tests carry it goes on, and a `[unit-test]` group is not checked (spec: test-markers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunOutcome
from tests.graph.branch_fakes import UNIT, agent_calls, build, prepared, titled
from tests.graph.test_build_path import limited
from tests.runner_fakes import Recorder

MISSING_REASON = "SELECTOR-REASON-1: test_new has no integration selector"


class SelectorAnswers:
    """The selector check as the runner binds it: answers from `answers` in order (the last one
    once they run out), each run recorded as the event `selector-check` in the recorder's events."""

    def __init__(self, recorder: Recorder, answers: list[tuple[bool, str]]) -> None:
        self.recorder = recorder
        self.answers = answers
        self.asked = 0
        # The agent calls made before each check: which group it ran for.
        self.after_calls: list[list[str]] = []

    def __call__(self, *, cwd: Path) -> tuple[bool, str]:
        self.after_calls.append(agent_calls(self.recorder.events))
        self.recorder.events.append("selector-check")
        answer = self.answers[min(self.asked, len(self.answers) - 1)]
        self.asked += 1
        return answer


def selector_build(
    tmp_path: Path, answers: list[tuple[bool, str]], **options: Any
) -> tuple[Recorder, SelectorAnswers, RunOutcome]:
    options.setdefault("groups", {"add-marker": titled(1)})
    options.setdefault("integration", (1,))
    recorder, _ = prepared(tmp_path, **options)
    selector = SelectorAnswers(recorder, answers)
    outcome = build(tmp_path, recorder, run_selector_check=selector, **recorder.overrides(tmp_path))
    return recorder, selector, outcome


def test_tests_that_carry_the_selector_go_on_to_the_implementation(tmp_path: Path) -> None:
    recorder, _, outcome = selector_build(tmp_path, [(True, "")])

    assert outcome.status == "open"
    assert recorder.events.count("selector-check") == 1
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl"]
    assert recorder.events.index("selector-check") < recorder.events.index("claude:impl")


def test_tests_without_the_selector_go_back_to_the_tests_step_with_the_reason(
    tmp_path: Path,
) -> None:
    recorder, _, outcome = selector_build(tmp_path, [(False, MISSING_REASON), (True, "")])

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:tests", "claude:tests", "claude:impl"]
    assert recorder.events.count("selector-check") == 2
    (returned,) = (prompt for prompt in recorder.prompts if MISSING_REASON in prompt)
    assert "Add the `integration` selector to each test named" in returned
    assert "fails with an assertion" not in returned


def test_the_returns_are_counted_against_max_check_rounds(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)}, integration=(1,))
    limited(max_check_rounds=1)
    selector = SelectorAnswers(recorder, [(False, MISSING_REASON)])

    outcome = build(tmp_path, recorder, run_selector_check=selector, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert recorder.events.count("selector-check") == 2, "the budget, no more"
    assert "claude:impl" not in recorder.events
    assert MISSING_REASON in recorder.store.get(UNIT).feedback


def test_a_unit_test_group_is_not_checked_for_the_selector(tmp_path: Path) -> None:
    recorder, selector, outcome = selector_build(
        tmp_path,
        [(True, "")],
        groups={"add-marker": titled(1, 2)},
        integration=(2,),
    )

    assert outcome.status == "open"
    assert recorder.events.count("selector-check") == 1, "the one integration-test group"
    assert selector.after_calls == [["claude:tests", "claude:impl", "claude:tests"]], (
        "it ran after group 2's tests step, not group 1's"
    )
