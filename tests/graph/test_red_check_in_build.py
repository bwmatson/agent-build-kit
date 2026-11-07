"""The build runs the red check at the tests commit, between the static checks of the tests and
the implementation: a test that passes goes back to the tests step with the reason, within
`max_check_rounds`, a test that fails with an assertion goes on, and a group with no tests commit
to judge does not run it; the pull request says "seen to fail" only for a check that ran (spec:
tdd-loop)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunOutcome
from tests.factories import activate_with
from tests.graph.branch_fakes import UNIT, agent_calls, build, key, prepared, titled
from tests.graph.test_build_path import limited
from tests.graph.test_remaining_paths import capturing
from tests.runner_fakes import Recorder

PASSED_REASON = "RED-REASON-1: test_new passed before any implementation existed"
COLLECTION_REASON = "RED-REASON-2: test_new could not be collected"
SEEN_TO_FAIL = "seen to fail"


class RedAnswers:
    """The red check as the runner binds it: answers from `answers` in order (the last one once
    they run out), each run recorded as the event `red-check` in the recorder's events."""

    def __init__(self, recorder: Recorder, answers: list[tuple[bool, str]]) -> None:
        self.recorder = recorder
        self.answers = answers
        self.asked = 0

    def __call__(self, *, cwd: Path) -> tuple[bool, str]:
        self.recorder.events.append("red-check")
        answer = self.answers[min(self.asked, len(self.answers) - 1)]
        self.asked += 1
        return answer


def red_build(
    tmp_path: Path, answers: list[tuple[bool, str]], **options: Any
) -> tuple[Recorder, RunOutcome]:
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)}, **options)
    red = RedAnswers(recorder, answers)
    outcome = build(tmp_path, recorder, run_red_check=red, **recorder.overrides(tmp_path))
    return recorder, outcome


def test_a_new_test_that_fails_with_an_assertion_goes_on_to_the_implementation(
    tmp_path: Path,
) -> None:
    recorder, outcome = red_build(tmp_path, [(True, "")])

    assert outcome.status == "open"
    assert recorder.events.count("red-check") == 1
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl"]
    stubs, red, impl = (
        recorder.events.index(e) for e in ("stub-checks", "red-check", "claude:impl")
    )
    assert stubs < red < impl


def test_a_new_test_that_passes_goes_back_to_the_tests_step_with_the_reason(
    tmp_path: Path,
) -> None:
    recorder, outcome = red_build(tmp_path, [(False, PASSED_REASON), (True, "")])

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:tests", "claude:tests", "claude:impl"]
    assert recorder.events.count("red-check") == 2
    assert any(PASSED_REASON in prompt for prompt in recorder.prompts)


def test_a_test_that_cannot_be_collected_goes_back_the_same_way(tmp_path: Path) -> None:
    recorder, _ = red_build(tmp_path, [(False, COLLECTION_REASON), (True, "")])

    assert agent_calls(recorder.events) == ["claude:tests", "claude:tests", "claude:impl"]
    assert any(COLLECTION_REASON in prompt for prompt in recorder.prompts)


def test_the_returns_are_counted_against_max_check_rounds(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)})
    limited(max_check_rounds=1)
    red = RedAnswers(recorder, [(False, PASSED_REASON)])

    outcome = build(tmp_path, recorder, run_red_check=red, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert recorder.events.count("red-check") == 2, "the budget, no more"
    assert agent_calls(recorder.events) == ["claude:tests", "claude:tests"]
    assert "claude:impl" not in recorder.events
    assert PASSED_REASON in recorder.store.get(UNIT).feedback


def test_a_group_with_no_tests_commit_to_judge_does_not_run_the_check(tmp_path: Path) -> None:
    recorder, outcome = red_build(
        tmp_path,
        [(True, "")],
        modes={
            key(1): "tests_and_code",
            key(2): "tests_only",
            key(3): "no_code",
            key(4): "refactor",
        },
        tests_only=(2,),
    )

    assert outcome.status == "open"
    assert recorder.events.count("red-check") == 1, "the one group that writes tests and code"


def test_the_pull_request_says_seen_to_fail_for_a_check_that_ran(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1)})
    activate_with(builders={"stubbed_tdd_commits": True}, review={"enabled": True})
    bodies: list[dict[str, str]] = []
    red = RedAnswers(recorder, [(False, PASSED_REASON), (True, "")])

    build(
        tmp_path,
        recorder,
        run_red_check=red,
        open_pr=capturing(recorder, bodies),
        **recorder.overrides(tmp_path),
    )

    assert recorder.events.count("red-check") == 2
    assert SEEN_TO_FAIL in bodies[0]["body"]
