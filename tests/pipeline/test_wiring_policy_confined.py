"""`ToolPolicy.confined` is set from the backend's coverage when the policy is built, and the hook
is registered with `--confined` only then (spec: sandbox-guard-fallback)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import build_argv
from tests.pipeline.test_wiring_sandbox import Recording, Unconfining, install, step


def hook_command(request: AgentRequest) -> str:
    argv = build_argv(request)
    settings = json.loads(argv[argv.index("--settings") + 1])
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def step_on(runtime: Recording, root: Path, main: Path) -> AgentRequest:
    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app")(
        "Go.", cwd=main, model=models().implement
    )
    (request,) = runtime.requests
    return request


def test_a_step_the_backend_confines_carries_a_confined_policy(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main)

    assert request.policy is not None
    assert request.policy.confined is True
    assert " --confined" in hook_command(request)


@pytest.mark.parametrize("why", ["sandbox-off", "backend-covers-less", "required-none"])
def test_a_step_that_runs_plain_carries_no_confined_flag(tmp_path: Path, why: str) -> None:
    (tmp_path / "confined").mkdir()
    (tmp_path / why).mkdir()
    sibling_root, sibling_main = install(tmp_path / "confined", enabled=True)
    sibling = step(sibling_root, sibling_main)
    root, main = install(
        tmp_path / why,
        enabled=why != "sandbox-off",
        required="none" if why == "required-none" else "process",
    )
    runtime = Unconfining() if why == "backend-covers-less" else Recording()

    request = step_on(runtime, root, main)

    assert sibling.policy is not None and sibling.policy.confined is True
    assert request.policy is not None
    assert request.policy.confined is False
    assert "--confined" not in hook_command(request)


def test_a_confined_step_still_carries_the_disallowed_tools(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main)

    assert request.policy is not None and request.policy.confined
    assert "--disallowedTools" in build_argv(request)
