"""An ACP run starts its agent, and every terminal its client starts, through the sandbox
backend's command when its request carries a sandbox policy (spec: sandbox-acp, group 1).

The agent is the kit's fake ACP agent (`acp_agent.py`), a real subprocess speaking the protocol,
started by the real `AcpRuntime` through the real Landlock launcher; the backend is wrapped only
to see what it was asked. There is no ACP agent on the development machine, so what an agent does
with its own file access is not tested here: that is the process wrap's, and the probe's.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.installation import load_installation
from agent_build_kit.runtimes import known_agents
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.sandboxes.policy import policy_entries, proxy_environment
from tests.runtimes.acp_agent import ENVIRONMENT, requests, use_command
from tests.runtimes.acp_sandbox_support import SECRETS, Recording, Scene, shell
from tests.sandboxes.landlock_support import CONNECT, require_network_rules
from tests.sandboxes.landlock_support import listening as listening_on

UNVERIFIED = "unverified against a real agent"


def printed_environment(output: str) -> dict[str, str]:
    pairs = (line.partition("=") for line in output.splitlines())
    return {name: value for name, _, value in pairs}


# --- the agent and its terminals start through the backend's command ---------------------


def test_the_agent_process_starts_through_the_backend_command(
    scene: Scene, backend: Recording
) -> None:
    scene.act()

    result = scene.run(scene.policy())

    assert result.ok, result.error
    assert backend.asked, "the agent was started without the backend's command"
    asked, argv = backend.asked[0]
    assert argv == scene.command
    assert asked.write == scene.policy().write


def test_a_terminal_starts_through_the_backend_command(scene: Scene, backend: Recording) -> None:
    scene.act(shell("echo hello"))

    scene.run(scene.policy())

    assert [argv for _, argv in backend.asked[1:]] == [["sh", "-c", "echo hello"]]
    assert scene.terminal()["output"].strip() == "hello"


def test_a_terminal_that_writes_a_protected_file_fails_and_leaves_it_unchanged(
    scene: Scene, backend: Recording
) -> None:
    scene.act(shell(f"echo changed > {scene.target}"))

    scene.run(scene.policy(), scoped=False)

    ran = scene.terminal()
    assert ran["exitCode"] != 0
    assert "denied" in ran["output"].lower()
    assert scene.target.read_text() == "original\n"


def test_a_terminal_that_writes_an_allowed_file_works(scene: Scene, backend: Recording) -> None:
    written = scene.worktree / "out.txt"
    scene.act(shell(f"echo written > {written}"))

    scene.run(scene.policy(), scoped=False)

    assert [argv[:2] for _, argv in backend.asked[1:]] == [["sh", "-c"]]
    assert scene.terminal()["exitCode"] == 0
    assert written.read_text() == "written\n"


def test_a_terminal_that_connects_directly_to_a_host_fails(
    scene: Scene, backend: Recording
) -> None:
    require_network_rules(backend.inner)
    with listening_on("127.0.0.1") as port:
        scene.act(
            {"terminal": sys.executable, "args": ["-c", CONNECT, "127.0.0.1", str(port)]},
        )

        scene.run(scene.policy(), scoped=False)

    assert scene.terminal()["output"].strip() == "PermissionError"


# --- the terminal's environment ----------------------------------------------------------


def test_the_terminal_environment_holds_the_proxy_variables_and_none_of_abk_s_secrets(
    scene: Scene, backend: Recording
) -> None:
    scene.act(shell("env"))

    scene.run(scene.policy(), scoped=False)

    seen = printed_environment(scene.terminal()["output"])
    asked, _ = backend.asked[-1]
    assert asked.proxy_port is not None
    for name, value in proxy_environment(asked.proxy_port).items():
        assert seen.get(name) == value, name
    assert "PATH" in seen
    for name in SECRETS:
        assert name not in seen, name


def test_the_agent_process_environment_holds_the_proxy_variables_and_none_of_abk_s_secrets(
    scene: Scene, backend: Recording
) -> None:
    asked_for = tuple(proxy_environment(1))
    scene.act(watch=(*SECRETS, *asked_for))

    result = scene.run(scene.policy())

    assert result.ok, result.error
    (seen,) = requests(scene.record, ENVIRONMENT)
    asked, _ = backend.asked[0]
    assert asked.proxy_port is not None
    for name, value in proxy_environment(asked.proxy_port).items():
        assert seen[name] == value, name
    for name in SECRETS:
        assert seen[name] is None, name


def test_the_terminal_environment_honours_the_env_argument(
    scene: Scene, backend: Recording
) -> None:
    scene.act({**shell("env"), "env": {"FROM_THE_AGENT": "yes"}})

    scene.run(scene.policy(), scoped=False)

    seen = printed_environment(scene.terminal()["output"])
    assert seen.get("FROM_THE_AGENT") == "yes"


# --- the client's file methods ------------------------------------------------------------


def test_read_text_file_serves_a_path_on_the_read_list(scene: Scene, backend: Recording) -> None:
    scene.act({"read": str(scene.worktree / "ok.txt")})

    scene.run(scene.policy())

    assert backend.asked, "the agent was started without the backend's command"
    [did] = requests(scene.record, "did/read")
    assert did["content"] == "fine\n"


def test_read_text_file_serves_a_path_the_policy_lists_only_for_writing(
    scene: Scene, backend: Recording
) -> None:
    policy = scene.write_only_policy()
    assert scene.worktree.resolve() in policy.write
    assert scene.worktree.resolve() not in policy.read
    scene.act({"read": str(scene.worktree / "ok.txt")})

    scene.run(policy)

    [did] = requests(scene.record, "did/read")
    assert did["content"] == "fine\n"


@pytest.mark.parametrize("policy_of", [Scene.policy, Scene.write_only_policy])
@pytest.mark.parametrize(
    "how",
    ["outside", "symlink", "dotdot"],
)
def test_read_text_file_refuses_what_the_policy_does_not_list(
    how: str, policy_of: Any, scene: Scene, backend: Recording
) -> None:
    path = {
        "outside": str(scene.hidden),
        "symlink": str(scene.worktree / "link.txt"),
        "dotdot": str(scene.worktree / ".." / "secret" / "token.txt"),
    }[how]
    scene.act({"read": path})

    scene.run(policy_of(scene))

    [did] = requests(scene.record, "did/read")
    assert "error" in did, did
    assert "hidden" not in str(did)


def test_the_client_s_file_write_checks_are_unchanged_because_the_kit_performs_the_write(
    scene: Scene, backend: Recording
) -> None:
    """The write is done by the kit's own process, which no sandbox confines, so the policy's
    write list cannot decide it: the worktree rule still does, whatever the list says."""
    inside = scene.worktree / "made.txt"
    outside = scene.protected / "made.txt"
    scene.act(
        {"write": str(inside), "content": "in\n"}, {"write": str(outside), "content": "out\n"}
    )

    scene.run(scene.policy(write_worktree=False))

    assert backend.asked, "the agent was started without the backend's command"
    written, refused = requests(scene.record, "did/write")
    assert written.get("ok") is True
    assert inside.read_text() == "in\n"
    assert "error" in refused
    assert not outside.exists()


# --- what is reported ---------------------------------------------------------------------


def test_the_runtime_reports_process_coverage_with_the_unverified_note() -> None:
    assert AcpRuntime.sandbox_coverage is Coverage.PROCESS
    assert UNVERIFIED in AcpRuntime.sandbox_note


def test_every_known_agent_lists_its_state_folders() -> None:
    for agent in known_agents.KNOWN_AGENTS:
        assert agent.state_folders, agent.name


def test_the_policy_grants_the_known_agent_s_state_folders(tmp_path: Path) -> None:
    agent = known_agents.KNOWN_AGENTS[0]
    root = tmp_path / "plan"
    root.mkdir()
    (root / "abk.yaml").write_text(
        yaml.safe_dump({"repos": {"app": {"path": str(tmp_path / "main"), "slug": "example/app"}}})
    )
    worktree = tmp_path / "wt"
    worktree.mkdir()

    installation = load_installation(root / "abk.yaml")  # which activates its own configuration
    use_command([agent.program])
    entries = policy_entries(
        installation,
        "app",
        worktree,
        runtime=AcpRuntime(),
        profile=object(),
    )

    def listed(kind: str) -> list[str]:
        return [e.value for e in entries if e.kind == kind and e.source == "runtime"]

    assert agent.state_folders
    for folder in agent.state_folders:
        expanded = str(Path.home() / folder)
        assert expanded in listed("write"), folder
        assert expanded in listed("read"), folder
