"""A Claude Code step starts through the sandbox backend's command when its request carries a
sandbox policy (spec: sandbox-claude-code, group 1).

The program is a stand-in `claude` script that records its argv and environment, started by the
real `spawn` through the real Landlock launcher; the backend is wrapped only to see what it was
asked.
"""

from __future__ import annotations

import json
import logging
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from agent_build_kit import claude_account, config, sandboxes
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import load_installation
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from agent_build_kit.sandboxes import Coverage, SandboxBackend, SandboxPolicy, unavailable
from agent_build_kit.sandboxes.policy import policy_entries, proxy_environment
from tests.sandboxes.landlock_support import policy_for, require_working

SECRETS = {
    "ABK_GATEWAY_MASTER_KEY": "gateway-secret",
    "ABK_GRAFANA_TOKEN": "grafana-secret",
    "AZURE_DEVOPS_EXT_PAT": "ado-secret",
}
PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")


def no_backend(name: str = "auto"):
    """`sandboxes.probe` on a machine where no backend works."""
    return unavailable.BACKEND, unavailable.BACKEND.availability()


class Recording:
    """The real backend, remembering each policy and argv it was asked to wrap."""

    def __init__(self, inner: SandboxBackend) -> None:
        self.inner = inner
        self.name = inner.name
        self.platform = inner.platform
        self.asked: list[tuple[SandboxPolicy, list[str]]] = []

    def availability(self):
        return self.inner.availability()

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        self.asked.append((policy, list(argv)))
        return self.inner.command(policy, argv)


class Scene:
    def __init__(self, root: Path) -> None:
        self.worktree = root / "worktree"
        self.record = root / "record"
        self.worktree.mkdir()
        self.record.mkdir()
        program = root / "agent-stand-in"
        program.write_text(
            "#!/bin/sh\n"
            "cat > /dev/null\n"
            f"printf '%s\\n' \"$@\" > {self.record}/argv\n"
            f"env > {self.record}/env\n"
            "echo done\n"
        )
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        self.program = program
        config.activate(
            WorkspaceConfig.model_validate(
                {"runtimes": {"claude_code": {"command": [str(program)]}}}
            )
        )
        self.root = root

    def policy(self, *, required: Coverage = Coverage.FILES) -> SandboxPolicy:
        base = policy_for([self.record, Path("/dev")], read=[self.root], required=required)
        return base.model_copy(update={"hosts": ("api.anthropic.com",)})

    def request(self, policy: SandboxPolicy | None) -> AgentRequest:
        return AgentRequest(
            prompt="Go.",
            role="implement",
            cwd=self.worktree,
            policy=ToolPolicy(sandbox=policy) if policy is not None else None,
        )

    def argv(self) -> list[str]:
        return (self.record / "argv").read_text().splitlines()

    def environment(self) -> dict[str, str]:
        pairs = (line.partition("=") for line in (self.record / "env").read_text().splitlines())
        return {name: value for name, _, value in pairs}


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    return Scene(tmp_path)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> Recording:
    real = sandboxes.get("landlock")
    require_working(real)
    recording = Recording(real)
    monkeypatch.setattr(sandboxes, "probe", lambda name="auto": (recording, real.availability()))
    return recording


def test_a_step_with_a_sandbox_policy_starts_through_the_backend_command(
    scene: Scene, backend: Recording
) -> None:
    policy = scene.policy()

    result = ClaudeCodeRuntime(execute=spawn).run(scene.request(policy))

    assert result.ok, result.error
    ((asked, argv),) = backend.asked
    assert argv[0] == str(scene.program)
    assert asked.write == policy.write
    assert (scene.record / "argv").exists()


def test_the_proxy_variables_reach_the_step_and_the_policy_names_the_proxy_port(
    scene: Scene, backend: Recording
) -> None:
    ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    ((asked, _),) = backend.asked
    assert asked.proxy_port is not None
    seen = scene.environment()
    for name, value in proxy_environment(asked.proxy_port).items():
        assert seen.get(name) == value, name


def test_the_step_does_not_see_abk_s_own_secrets(scene: Scene, backend: Recording) -> None:
    ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    seen = scene.environment()
    assert "PATH" in seen
    for name in SECRETS:
        assert name not in seen, name


def test_the_per_run_settings_turn_claude_code_s_own_sandbox_off(
    scene: Scene, backend: Recording
) -> None:
    ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    argv = scene.argv()
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is False


def test_the_runtime_reports_process_coverage() -> None:
    assert ClaudeCodeRuntime.sandbox_coverage is Coverage.PROCESS


def test_the_policy_grants_the_account_folder_the_temp_folder_and_the_device_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plan"
    root.mkdir()
    (root / "abk.yaml").write_text(
        yaml.safe_dump({"repos": {"app": {"path": str(tmp_path / "main"), "slug": "example/app"}}})
    )
    worktree = tmp_path / "wt"
    worktree.mkdir()

    entries = policy_entries(
        load_installation(root / "abk.yaml"),
        "app",
        worktree,
        runtime=ClaudeCodeRuntime(),
        profile=object(),
    )

    def listed(kind: str) -> list[str]:
        return [e.value for e in entries if e.kind == kind and e.source == "runtime"]

    account = str(claude_account.home())
    assert account in listed("write")
    assert account in listed("read")
    assert "/tmp" in listed("write")
    assert "/dev" in listed("write")
    assert "api.anthropic.com" in listed("hosts")


def planned_entries(tmp_path: Path, account: claude_account.Account | None):
    root = tmp_path / "plan"
    root.mkdir()
    (root / "abk.yaml").write_text(
        yaml.safe_dump({"repos": {"app": {"path": str(tmp_path / "main"), "slug": "example/app"}}})
    )
    return policy_entries(
        load_installation(root / "abk.yaml"),
        "app",
        tmp_path,
        runtime=ClaudeCodeRuntime(),
        profile=object(),
        account=account,
    )


def test_the_policy_grants_the_folder_and_state_file_of_the_account_the_step_runs_as(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "acct"
    account = claude_account.Account(label="kit", config_dir=folder)

    entries = planned_entries(tmp_path, account)

    for kind in ("write", "read"):
        listed = [e.value for e in entries if e.kind == kind and e.source == "runtime"]
        assert str(folder) in listed
        assert str(folder / ".claude.json") in listed
        assert str(claude_account.home()) not in listed


def test_the_default_account_s_state_file_is_granted(tmp_path: Path) -> None:
    entries = planned_entries(tmp_path, None)

    for kind in ("write", "read"):
        listed = [e.value for e in entries if e.kind == kind and e.source == "runtime"]
        assert str(claude_account.state_file()) in listed


class Capture:
    """An `execute` that keeps the sandbox policy it was given."""

    def __init__(self) -> None:
        self.sandbox: SandboxPolicy | None = None

    def __call__(self, argv, *, sandbox=None, **_):
        self.sandbox = sandbox
        return subprocess.CompletedProcess(argv, 0, "done\n", "")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"ANTHROPIC_BASE_URL": "http://gateway.example:4000"}, "gateway.example"),
        ({}, "api.anthropic.com"),
    ],
    ids=["gateway", "default"],
)
def test_the_policy_hosts_include_the_model_endpoint_the_run_calls(
    tmp_path: Path, env: dict[str, str], expected: str
) -> None:
    capture = Capture()
    base = SandboxPolicy(
        write=(tmp_path,), read=(), hosts=("api.anthropic.com",), required=Coverage.FILES
    )
    request = AgentRequest(prompt="Go.", cwd=tmp_path, env=env, policy=ToolPolicy(sandbox=base))

    ClaudeCodeRuntime(execute=capture).run(request)

    assert capture.sandbox is not None
    assert expected in capture.sandbox.hosts
    assert len(set(capture.sandbox.hosts)) == len(capture.sandbox.hosts)
    if not env:
        assert capture.sandbox.hosts == base.hosts


@pytest.mark.parametrize("policy", [None, ToolPolicy()], ids=["no-policy", "no-sandbox"])
def test_a_step_without_a_sandbox_policy_runs_as_it_did(
    scene: Scene, monkeypatch: pytest.MonkeyPatch, policy: ToolPolicy | None
) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("a backend was asked for a step with no sandbox policy")

    monkeypatch.setattr(sandboxes, "probe", refuse)
    monkeypatch.setattr(sandboxes, "detect", refuse)

    request = scene.request(None).model_copy(update={"policy": policy})
    result = ClaudeCodeRuntime(execute=spawn).run(request)

    assert result.ok, result.error
    argv = scene.argv()
    assert "sandbox" not in json.loads(argv[argv.index("--settings") + 1])
    seen = scene.environment()
    for name, value in SECRETS.items():
        assert seen.get(name) == value
    assert not any(name in seen for name in PROXY_VARIABLES)


def test_a_backend_that_cannot_start_fails_the_step_with_the_cause(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandboxes, "probe", no_backend)

    result = ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    assert not result.ok
    assert unavailable.CAUSE in result.error
    assert not (scene.record / "argv").exists()


def test_under_required_none_a_step_that_cannot_be_confined_runs_and_warns(
    scene: Scene, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sandboxes, "probe", no_backend)
    caplog.set_level(logging.WARNING)

    result = ClaudeCodeRuntime(execute=spawn).run(
        scene.request(scene.policy(required=Coverage.NONE))
    )

    assert result.ok, result.error
    assert (scene.record / "argv").exists()
    assert unavailable.CAUSE in caplog.text


def test_a_confined_step_cannot_write_outside_the_policy(scene: Scene, backend: Recording) -> None:
    """The real launcher is in the way: a write the policy does not grant fails."""
    protected = scene.root / "protected.txt"
    protected.write_text("original\n")
    script = scene.program.read_text() + f"echo changed > {protected}\n"
    scene.program.write_text(script)

    ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    assert protected.read_text() == "original\n"


def probing(monkeypatch: pytest.MonkeyPatch, coverage: Coverage | None = None):
    """Replace `sandboxes.probe` with a recorder of the names it is asked for, answering with
    the real backend and, when `coverage` is given, an ok availability of that coverage."""
    real = sandboxes.get("landlock")
    require_working(real)
    recording = Recording(real)
    names: list[str] = []

    def probe(name: str = "auto"):
        names.append(name)
        found = real.availability()
        if coverage is not None:
            found = found.model_copy(update={"coverage": coverage, "cause": "kernel too old"})
        return recording, found

    monkeypatch.setattr(sandboxes, "probe", probe)
    return recording, names


@pytest.mark.parametrize(
    ("sandbox", "expected"),
    [({"enabled": True, "backend": "landlock"}, "landlock"), ({"enabled": True}, "auto")],
    ids=["named", "default"],
)
def test_the_backend_is_the_one_the_configuration_names(
    scene: Scene, monkeypatch: pytest.MonkeyPatch, sandbox: dict, expected: str
) -> None:
    config.activate(
        WorkspaceConfig.model_validate(
            {
                "sandbox": sandbox,
                "runtimes": {"claude_code": {"command": [str(scene.program)]}},
            }
        )
    )
    _, names = probing(monkeypatch)

    ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy()))

    assert names == [expected]


@pytest.mark.parametrize(
    ("required", "warned"),
    [(Coverage.PROCESS, True), (Coverage.FILES, False)],
    ids=["short", "enough"],
)
def test_a_backend_that_reaches_less_than_required_runs_the_step_and_warns(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    required: Coverage,
    warned: bool,
) -> None:
    recording, _ = probing(monkeypatch, coverage=Coverage.FILES)
    caplog.set_level(logging.WARNING)

    result = ClaudeCodeRuntime(execute=spawn).run(scene.request(scene.policy(required=required)))

    assert result.ok, result.error
    assert len(recording.asked) == 1
    shortfalls = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "files" in r.getMessage()
        and "process" in r.getMessage()
    ]
    assert bool(shortfalls) is warned
