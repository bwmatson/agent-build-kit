"""The same `SandboxPolicy` under the Claude Code path and the ACP path gives the same outcomes
for a protected write, an allowed write and a direct connection, and each runtime reports the
coverage that was observed (spec: sandbox-acp, group 2).

The Claude Code path is a stand-in `claude` script that runs the command, started by the real
`spawn` through the real Landlock launcher; the ACP path is the kit's fake agent asking its client
for a terminal. The backend is the real one.
"""

from __future__ import annotations

import shlex
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from agent_build_kit import config
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.runtimes import AgentRequest, AgentRuntime, ToolPolicy, policy_check
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from agent_build_kit.sandboxes import SandboxPolicy
from tests.conftest import make_installation
from tests.runtimes.acp_sandbox_support import Recording, Scene
from tests.sandboxes.landlock_support import CONNECT, listening, require_network_rules


class Outcome(NamedTuple):
    exit_code: int
    output: str


Attempt = Callable[[SandboxPolicy, list[str]], Outcome]


class Path_(NamedTuple):
    """One runtime's way of running a command under a policy."""

    runtime: AgentRuntime
    attempt: Attempt


def claude_attempt(scene: Scene) -> Path_:
    program = scene.record_dir / "claude-stand-in"
    out, code = scene.record_dir / "out", scene.record_dir / "code"

    def attempt(policy: SandboxPolicy, argv: list[str]) -> Outcome:
        program.write_text(
            "#!/bin/sh\n"
            "cat > /dev/null\n"
            f"{shlex.join(argv)} > {out} 2>&1\n"
            f"echo $? > {code}\n"
            "echo done\n"
        )
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        config.activate(
            WorkspaceConfig.model_validate(
                {"runtimes": {"claude_code": {"command": [str(program)]}}}
            )
        )
        result = ClaudeCodeRuntime(execute=spawn).run(
            AgentRequest(
                prompt="Go.",
                role="implement",
                cwd=scene.worktree,
                policy=ToolPolicy(sandbox=policy),
            )
        )
        assert result.ok, result.error
        return Outcome(int(code.read_text()), out.read_text())

    return Path_(ClaudeCodeRuntime(), attempt)


def acp_attempt(scene: Scene) -> Path_:
    def attempt(policy: SandboxPolicy, argv: list[str]) -> Outcome:
        scene.act({"terminal": argv[0], "args": argv[1:]})
        scene.run(policy, scoped=False)
        ran = scene.terminal()
        return Outcome(ran["exitCode"], ran["output"])

    return Path_(AcpRuntime(), attempt)


@pytest.fixture(params=["claude_code", "acp"])
def path(request: pytest.FixtureRequest, scene: Scene, backend: Recording) -> Path_:
    return {"claude_code": claude_attempt, "acp": acp_attempt}[request.param](scene)


def reported(path: Path_, tmp_path: Path) -> str:
    return policy_check.sandbox_coverage_text(path.runtime, make_installation(tmp_path / "plan"))


def test_a_write_to_a_protected_file_fails_the_same_way_under_both_runtimes(
    path: Path_, scene: Scene, tmp_path: Path
) -> None:
    outcome = path.attempt(scene.policy(), ["sh", "-c", f"echo changed > {scene.target}"])

    assert outcome.exit_code != 0
    assert "denied" in outcome.output.lower()
    assert scene.target.read_text() == "original\n"
    assert reported(path, tmp_path).startswith("process")


def test_a_write_to_an_allowed_file_works_the_same_way_under_both_runtimes(
    path: Path_, scene: Scene, tmp_path: Path
) -> None:
    written = scene.worktree / "out.txt"

    outcome = path.attempt(scene.policy(), ["sh", "-c", f"echo written > {written}"])

    assert outcome.exit_code == 0
    assert written.read_text() == "written\n"
    assert reported(path, tmp_path).startswith("process")


def test_a_direct_connection_is_refused_the_same_way_under_both_runtimes(
    path: Path_, scene: Scene, backend: Recording, tmp_path: Path
) -> None:
    require_network_rules(backend.inner)
    with listening("127.0.0.1") as port:
        outcome = path.attempt(
            scene.policy(), [sys.executable, "-c", CONNECT, "127.0.0.1", str(port)]
        )

    assert outcome.output.strip() == "PermissionError"
    assert reported(path, tmp_path).startswith("process")


def test_only_the_acp_runtime_reports_the_unverified_note(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "plan")

    claude = policy_check.sandbox_coverage_text(ClaudeCodeRuntime(), installation)
    acp = policy_check.sandbox_coverage_text(AcpRuntime(), installation)

    assert claude == "process"
    assert acp == "process (unverified against a real agent)"
