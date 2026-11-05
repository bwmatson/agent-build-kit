"""What a build hands the agent, the verdict and the pull request for a unit with a group that has
no tests step: its implementation starts a session of its own, and a unit with no tests-first
group neither claims the tests came first nor is floored for want of that (spec:
group-build-modes)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.verdict_record import VERDICTS, latest_verdict
from tests.factories import activate_with
from tests.graph.branch_fakes import UNIT, build, key, prepared, titled
from tests.graph.test_remaining_paths import capturing
from tests.graph.test_session_continuation import Sessions, agents

SEEN_TO_FAIL = "seen to fail"


def opened_body(tmp_path: Path, modes: dict[str, str]) -> tuple[str, str]:
    """The body of the pull request a two-group unit with these modes opens, and the reason of
    the verdict recorded for it."""
    recorder, _ = prepared(tmp_path, groups={"add-marker": titled(1, 2)}, modes=modes)
    activate_with(builders={"stubbed_tdd_commits": True}, review={"enabled": True})
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies), **recorder.overrides(tmp_path))

    entry = latest_verdict(recorder.store.path.with_name(VERDICTS), UNIT)
    assert bodies, "the unit reached a pull request"
    assert entry is not None, "a verdict was recorded"
    return bodies[0]["body"], entry.reason


def test_a_group_with_no_tests_step_does_not_continue_the_session_of_the_previous_group(
    tmp_path: Path,
) -> None:
    recorder, _ = prepared(
        tmp_path,
        groups={"add-marker": titled(1, 2)},
        modes={key(1): "tests_and_code", key(2): "no_code"},
    )
    runtime = Sessions()

    build(tmp_path, recorder, **{**recorder.overrides(tmp_path), **agents(runtime)})

    *_, second = [request for request in runtime.built if "task group(s) 2" in request.prompt]
    assert second.resume_session == "", "a new session, not the tests' session"
    assert "The tests are written" not in second.prompt
    assert "task group(s) 2" in second.prompt


def test_the_pull_request_of_a_unit_with_no_tests_first_group_does_not_claim_tests_first(
    tmp_path: Path,
) -> None:
    body, reason = opened_body(tmp_path, {key(1): "no_code", key(2): "refactor"})

    assert SEEN_TO_FAIL not in body
    assert "red-first" not in reason


def test_the_pull_request_of_a_unit_mixing_modes_keeps_the_claim_for_its_tests_first_group(
    tmp_path: Path,
) -> None:
    body, reason = opened_body(tmp_path, {key(1): "tests_and_code", key(2): "no_code"})

    assert SEEN_TO_FAIL in body
    assert "red-first" not in reason
