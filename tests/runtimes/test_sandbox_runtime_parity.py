"""The same `SandboxPolicy` under the Claude Code path and the ACP path gives the same outcomes
for a protected write, an allowed write and a direct connection, and each runtime reports the
coverage that was observed (spec: sandbox-acp, group 2).

The Claude Code path is a stand-in `claude` script that runs the command, started by the real
`spawn` through the real Landlock launcher; the ACP path is the kit's fake agent asking its client
for a terminal. The backend is the real one.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from agent_build_kit.runtimes import AgentRequest, AgentRuntime, ToolPolicy, policy_check
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from agent_build_kit.sandboxes import SandboxPolicy
from tests.conftest import make_installation
from tests.runtimes.acp_sandbox_support import Recording, Scene, claude_stand_in
from tests.sandboxes.landlock_support import CONNECT, listening, require_network_rules


class Outcome(NamedTuple):
    exit_code: int
    output: str


Attempt = Callable[[SandboxPolicy, list[str]], Outcome]


class RuntimeUnderTest(NamedTuple):
    """One runtime and its way of running a command under a policy."""

    runtime: AgentRuntime
    attempt: Attempt


def claude_attempt(acp_scene: Scene) -> RuntimeUnderTest:
    out, code = acp_scene.record_dir / "out", acp_scene.record_dir / "code"

    def attempt(policy: SandboxPolicy, argv: list[str]) -> Outcome:
        claude_stand_in(
            acp_scene.record_dir / "claude-stand-in",
            f"{shlex.join(argv)} > {out} 2>&1\necho $? > {code}\necho done\n",
        )
        result = ClaudeCodeRuntime(execute=spawn).run(
            AgentRequest(
                prompt="Go.",
                role="implement",
                cwd=acp_scene.worktree,
                policy=ToolPolicy(sandbox=policy),
            )
        )
        assert result.ok, result.error
        return Outcome(int(code.read_text()), out.read_text())

    return RuntimeUnderTest(ClaudeCodeRuntime(), attempt)


def acp_attempt(acp_scene: Scene) -> RuntimeUnderTest:
    def attempt(policy: SandboxPolicy, argv: list[str]) -> Outcome:
        acp_scene.act({"terminal": argv[0], "args": argv[1:]})
        acp_scene.run(policy, scoped=False)
        ran = acp_scene.terminal()
        return Outcome(ran["exitCode"], ran["output"])

    return RuntimeUnderTest(AcpRuntime(), attempt)


@pytest.fixture(params=["claude_code", "acp"])
def runtime_under_test(
    request: pytest.FixtureRequest, acp_scene: Scene, backend: Recording
) -> RuntimeUnderTest:
    return {"claude_code": claude_attempt, "acp": acp_attempt}[request.param](acp_scene)


def reported(under_test: RuntimeUnderTest, tmp_path: Path) -> str:
    return policy_check.sandbox_coverage_text(
        under_test.runtime, make_installation(tmp_path / "plan")
    )


def test_a_write_to_a_protected_file_fails_the_same_way_under_both_runtimes(
    runtime_under_test: RuntimeUnderTest, acp_scene: Scene, tmp_path: Path
) -> None:
    outcome = runtime_under_test.attempt(
        acp_scene.policy(), ["sh", "-c", f"echo changed > {acp_scene.target}"]
    )

    assert outcome.exit_code != 0
    assert "denied" in outcome.output.lower()
    assert acp_scene.target.read_text() == "original\n"
    assert reported(runtime_under_test, tmp_path).startswith("process")


def test_a_write_to_an_allowed_file_works_the_same_way_under_both_runtimes(
    runtime_under_test: RuntimeUnderTest, acp_scene: Scene, tmp_path: Path
) -> None:
    written = acp_scene.worktree / "out.txt"

    outcome = runtime_under_test.attempt(
        acp_scene.policy(), ["sh", "-c", f"echo written > {written}"]
    )

    assert outcome.exit_code == 0
    assert written.read_text() == "written\n"
    assert reported(runtime_under_test, tmp_path).startswith("process")


def test_a_direct_connection_is_refused_the_same_way_under_both_runtimes(
    runtime_under_test: RuntimeUnderTest, acp_scene: Scene, backend: Recording, tmp_path: Path
) -> None:
    require_network_rules(backend.inner)
    with listening("127.0.0.1") as port:
        outcome = runtime_under_test.attempt(
            acp_scene.policy(), [sys.executable, "-c", CONNECT, "127.0.0.1", str(port)]
        )

    assert outcome.output.strip() == "PermissionError"
    assert reported(runtime_under_test, tmp_path).startswith("process")


def test_only_the_acp_runtime_reports_the_unverified_note(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "plan")

    claude = policy_check.sandbox_coverage_text(ClaudeCodeRuntime(), installation)
    acp = policy_check.sandbox_coverage_text(AcpRuntime(), installation)

    assert claude == "process"
    assert acp == "process (unverified against a real agent)"
