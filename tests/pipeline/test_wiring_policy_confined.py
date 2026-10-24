"""`ToolPolicy.confined` is set from the backend's coverage when the policy is built, and the hook
is registered with `--confined` only then (spec: sandbox-guard-fallback)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.wiring import build_run_review
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import build_argv
from tests.pipeline.test_wiring_sandbox import Recording, Unconfining, install, step


def hook_command(request: AgentRequest) -> str:
    argv = build_argv(request)
    settings = json.loads(argv[argv.index("--settings") + 1])
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def review_step(root: Path, main: Path) -> AgentRequest:
    runtime = Recording()
    build_run_review(runtime=runtime, planning_repo=root, sandbox_repo="app")(cwd=main)
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

    request = step(root, main, runtime)

    assert sibling.policy is not None and sibling.policy.confined is True
    assert request.policy is not None
    assert request.policy.confined is False
    assert "--confined" not in hook_command(request)


def test_a_confined_step_still_carries_the_disallowed_tools(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main)

    assert request.policy is not None and request.policy.confined
    assert "--disallowedTools" in build_argv(request)


def test_a_read_only_role_is_granted_no_edit_tool_whether_or_not_it_is_confined(
    tmp_path: Path,
) -> None:
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    on = review_step(*install(tmp_path / "on", enabled=True))
    off = review_step(*install(tmp_path / "off", enabled=False))

    assert on.policy is not None and off.policy is not None
    assert (on.policy.confined, off.policy.confined) == (True, False)
    assert on.allowed_tools == off.allowed_tools
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert tool not in on.allowed_tools.split()
