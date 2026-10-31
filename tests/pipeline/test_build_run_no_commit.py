"""A build run may not commit: the pipeline commits what the agent leaves in the worktree (spec:
build-agent-does-not-commit). The policy is the build run's, so each role that goes through it
(tests, implement, rework, port, fix rounds) carries it, and the runtimes apply it from there."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import models
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest
from tests.pipeline.test_wiring_sandbox import Recording, install


def request_of(tmp_path: Path) -> AgentRequest:
    root, main = install(tmp_path, enabled=False)
    runtime = Recording()
    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app")(
        "Go.", cwd=main, model=models().implement
    )
    (request,) = runtime.requests
    return request


def test_the_policy_of_a_build_run_refuses_commits(tmp_path: Path) -> None:
    request = request_of(tmp_path)

    assert request.policy is not None
    assert request.policy.no_commit


def test_the_build_run_keeps_the_rest_of_its_policy(tmp_path: Path) -> None:
    """The refusal is added to the policy, not in place of what it already carries."""
    request = request_of(tmp_path)

    assert request.policy is not None
    assert request.policy.specs_dir is not None
    assert request.policy.branch_prefix
