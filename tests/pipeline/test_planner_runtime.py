"""The planner's graph call reaches its agent through the runtime seam.

It used to run its own `claude` process with nothing shared with a build. It
now sends a request like every other step and reads the outcome the same way:
a refusal for a spent window is a rate limit, any other failed run is a failed
planning attempt that says what the CLI said — never a transcript parsed as
though it were a plan.
"""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, build_prompt, plan_round
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_argv import flags

CHANGES = {"add-marker": "## 1. [app] [tier1] Register the marker\n"}
IN_FLIGHT = [{"id": "other/1", "repo": "app", "branch": "spec/other/1", "state": "in_review"}]
PLAN = {
    "units": [
        {
            "id": "add-marker/1",
            "change": "add-marker",
            "title": "Register the marker",
            "repo": "app",
            "tier": "tier1",
            "depends_on": [],
            "estimated_lines": 120,
            "groups": [1],
        }
    ]
}


def test_the_graph_call_runs_through_the_runtime_it_is_given() -> None:
    """No worktree and nothing granted beyond its (empty) tool list: it
    answers from its prompt alone."""
    runtime = StandInRuntime(answer=json.dumps(PLAN))

    units = plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime).units

    assert [unit.id for unit in units] == ["add-marker/1"]
    request = runtime.request
    assert request.prompt == build_prompt(CHANGES, IN_FLIGHT)
    assert request.cwd is None
    assert request.permission_mode == "allowed_tools_only"
    assert request.allowed_tools == ""
    assert request.policy is None


def test_under_claude_code_the_graph_call_sends_the_command_it_sent_before() -> None:
    fake = FakeClaude(stdout=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=ClaudeCodeRuntime(execute=fake))

    assert flags(fake.argv, build_prompt(CHANGES, IN_FLIGHT)) == {
        "-p": None,
        "--output-format": "text",
    }
    assert fake.calls[0][1] is None


def test_a_refused_graph_call_is_a_rate_limit() -> None:
    """The same interpretation a build run gets: the window is spent, and it
    says when it resets. A text-mode call prints the refusal as a plain line."""
    fake = FakeClaude(stdout="Claude AI usage limit reached|1919763200\n", returncode=1)

    with pytest.raises(RateLimited) as caught:
        plan_round(changes=CHANGES, in_flight=[], runtime=ClaudeCodeRuntime(execute=fake))

    assert caught.value.resets_at is not None
    assert caught.value.resets_at.year == 2030


def test_a_failed_graph_call_fails_the_attempt_on_what_the_cli_said() -> None:
    """Not a complaint that the output held no plan: the run failed, and the
    attempt is recorded as failing for the reason the CLI gave."""
    fake = FakeClaude(stderr="Error: Stream closed before the turn ended", returncode=1)

    with pytest.raises(PlannerError, match="Stream closed before the turn ended"):
        plan_round(changes=CHANGES, in_flight=[], runtime=ClaudeCodeRuntime(execute=fake))


def test_a_failed_run_is_not_read_as_a_plan() -> None:
    """Whatever text a failed run left behind, it schedules nothing."""
    runtime = StandInRuntime(ok=False, answer=json.dumps(PLAN), error="claude exited 1: broken")

    with pytest.raises(PlannerError, match="broken"):
        plan_round(changes=CHANGES, in_flight=[], runtime=runtime)


def test_with_no_runtime_given_the_graph_call_uses_the_active_one() -> None:
    """Not a `claude` process of its own: the default is the workspace's
    runtime, whose real executor the suite refuses."""
    with pytest.raises(AssertionError, match="inject `execute=`"):
        plan_round(changes=CHANGES, in_flight=[])
