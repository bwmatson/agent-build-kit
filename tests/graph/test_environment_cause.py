"""A unit blocked by the environment fails with its own cause before any fix agent
runs, and a unit's own failure never takes it (spec: pipeline-environment).

The environment's `check` is a real child process (`tests/environment_fakes.py`);
tier 1 is faked where the runner binds it, as in the other graph tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW
from tests.conftest import make_installation
from tests.environment_fakes import FakeEnvironment, environment_cause
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

UNIT = "add-marker/1"
RESUME = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="environment restored"
)


def managed(tmp_path: Path) -> FakeEnvironment:
    """The planning repository the runner is given, with the fake environment active."""
    env = FakeEnvironment(tmp_path / "control")
    make_installation(tmp_path / "meta", environment=env.config())
    return env


def tier1_events(recorder: Recorder) -> list[str]:
    return [event for event in recorder.events if event.startswith("tier1")]


@pytest.mark.parametrize("commits", [1, 0], ids=["checks before review", "tier 1 for no work"])
def test_a_failing_check_fails_the_unit_with_the_environment_cause_before_tier_1(
    tmp_path: Path, commits: int
) -> None:
    env = managed(tmp_path)
    env.break_it()
    recorder = fresh(tmp_path, commits_from_impl=commits)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.FAILED
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (FAILED, environment_cause())
    assert stored.feedback == "", "nothing for an agent to fix is saved"
    assert tier1_events(recorder) == [], "tier 1 was not run on a broken environment"
    assert "claude:fix_checks" not in recorder.events
    assert "review" not in recorder.events


@pytest.mark.parametrize("commits", [1, 0], ids=["checks before review", "tier 1 for no work"])
def test_a_failing_pipeline_command_with_a_check_that_fails_then_spends_no_fix_round(
    tmp_path: Path, commits: int
) -> None:
    env = managed(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=commits)

    def breaks_the_environment(*, cwd: Path, base: str = "main", whole_repo: bool = False):
        recorder.events.append("tier1")
        env.break_it()
        return False, "error: executable `ruff` was not found"

    outcome = tick(tmp_path, recorder, run_tier1=breaks_the_environment)

    assert outcome.status == RunStatus.FAILED
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (FAILED, environment_cause())
    assert stored.feedback == ""
    assert "claude:fix_checks" not in recorder.events
    assert recorder.events.count("tier1") == 1


def test_a_units_own_import_error_with_a_passing_check_goes_to_the_fix_round(
    tmp_path: Path,
) -> None:
    env = managed(tmp_path)
    recorder = fresh(tmp_path)
    recorder.tier1_results = [
        (False, "ImportError: cannot import name 'widget' from 'app'"),
        (True, ""),
    ]

    outcome = tick(tmp_path, recorder)

    assert env.calls().count("check") >= 2, "the check was asked again when the command failed"
    assert "claude:fix_checks" in recorder.events
    assert any("cannot import name 'widget'" in prompt for prompt in recorder.prompts)
    assert outcome.status == "open"
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) != (FAILED, environment_cause())


def test_a_resumed_unit_that_meets_a_failing_check_again_returns_to_the_cause_without_an_agent(
    tmp_path: Path,
) -> None:
    env = managed(tmp_path)
    env.break_it()
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    prompts = len(recorder.prompts)

    tick(tmp_path, recorder, event=RESUME)
    tick(tmp_path, recorder)

    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (FAILED, environment_cause())
    assert len(recorder.prompts) == prompts, "no agent ran for the second failure"
    assert tier1_events(recorder) == []

    env.mend()
    tick(tmp_path, recorder, event=RESUME)
    outcome = tick(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.store.get(UNIT).state == IN_REVIEW
    assert "claude:fix_checks" not in recorder.events
