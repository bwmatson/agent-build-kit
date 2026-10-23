"""The policy follows the step's tier: a unit-test or integration step is never granted a
loopback port, a service port or a container socket, and an e2e-test step is granted the
repo's `tests.e2e_sandbox` lists (spec: sandbox-e2e-policy)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.sandboxes import Coverage, SandboxPolicy, landlock, launcher
from tests.sandboxes.landlock_support import launcher_args
from tests.sandboxes.policy_support import Scene

LISTS = {
    "read": ["fixtures"],
    "write": ["run"],
    "hosts": ["registry.example.test"],
    "ports": [5432],
}
LOCAL = {
    "repos": {
        "app": {
            "tests": {
                "e2e_sandbox": {"hosts": ["mirror.example.test"], "ports": [6379], "write": ["tmp"]}
            }
        }
    }
}


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def granted_text(policy: SandboxPolicy) -> str:
    return " ".join(
        [*map(str, policy.write), *map(str, policy.read), *policy.hosts, *map(str, policy.ports)]
    )


def restricted_with(policy: SandboxPolicy) -> Mapping[str, list[str]]:
    """The lists the launcher hands the kernel for `policy`, as the Landlock backend writes it."""
    lists: list[Mapping[str, list[str]]] = []
    launcher.main(
        launcher_args(landlock.BACKEND.command(policy, ["true"])),
        restrict=lists.append,
        execvp=lambda program, argv: None,
    )
    (given,) = lists
    return given


@pytest.mark.parametrize("tier", [TestTier.UNIT_TEST, TestTier.INTEGRATION_TEST])
def test_a_unit_test_or_integration_step_gets_nothing_a_service_needs(
    scene: Scene, tier: TestTier
) -> None:
    policy = scene.policy(tests={"e2e_sandbox": LISTS}, local=LOCAL, tier=tier)

    assert policy.ports == ()
    text = granted_text(policy)
    for refused in ("127.0.0.1", "localhost", "docker.sock", "registry.example.test", "5432"):
        assert refused not in text
    assert (scene.worktree / "run").resolve() not in policy.write


def test_an_e2e_step_adds_the_repo_s_lists_to_the_unit_test_policy(scene: Scene) -> None:
    unit = scene.policy(tests={"e2e_sandbox": LISTS}, tier=TestTier.UNIT_TEST)
    e2e = scene.policy(tests={"e2e_sandbox": LISTS}, tier=TestTier.E2E_TEST)

    assert set(unit.write) <= set(e2e.write)
    assert (scene.worktree / "run").resolve() in e2e.write
    assert (scene.worktree / "fixtures").resolve() in e2e.read
    assert "registry.example.test" in e2e.hosts
    assert e2e.ports == (5432,)
    assert e2e.required == unit.required


def test_the_machine_s_lists_from_the_local_file_join_the_committed_ones(scene: Scene) -> None:
    policy = scene.policy(tests={"e2e_sandbox": LISTS}, local=LOCAL, tier=TestTier.E2E_TEST)

    assert policy.ports == (5432, 6379)
    named = [h for h in policy.hosts if h.endswith(".example.test")]
    assert named == ["registry.example.test", "mirror.example.test"]
    assert (scene.worktree / "tmp").resolve() in policy.write


def test_an_e2e_step_of_a_repo_with_no_lists_runs_under_the_unit_test_policy(
    scene: Scene,
) -> None:
    unit = scene.policy(tier=TestTier.UNIT_TEST)
    e2e = scene.policy(tier=TestTier.E2E_TEST)

    assert e2e == unit


def test_the_landlock_tcp_rule_lists_the_proxy_port_and_the_e2e_ports() -> None:
    policy = SandboxPolicy(
        write=(),
        read=(),
        hosts=(),
        required=Coverage.PROCESS,
        proxy_port=3128,
        ports=(5432, 6379),
    )

    given = restricted_with(policy)

    assert given["proxy_port"] == ["3128"]
    assert given["port"] == ["5432", "6379"]


def test_a_policy_with_no_e2e_ports_adds_no_port_rule_beside_the_proxy_s() -> None:
    policy = SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.FILES, proxy_port=3128)

    given = restricted_with(policy)

    assert given["proxy_port"] == ["3128"]
    assert given["port"] == []
