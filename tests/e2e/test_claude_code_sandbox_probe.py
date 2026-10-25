"""A real `claude -p` step under the sandbox is confined (spec: sandbox-claude-code, group 2).

The runtime is the real Claude Code on this host, started by the real `spawn` through the real
sandbox backend and allowlist proxy, in a throwaway git checkout on a unit-style branch beside a
protected file standing for the planning repo's configuration. The policy is the one the pipeline
builds (`build_policy`), so a path or host the runtime or profile leaves out shows up here. The
step runs as the account the environment names, as the kit's other live tests do. Each probed
command leaves its evidence in the worktree, and that evidence is what is asserted, not what the
model says:

- the step answers, so it reached the model through the proxy: the hosts the proxy connected to
  include the model endpoint;
- a file in the worktree is written;
- a shell command's write to the protected file fails with a permission error and the file is
  unchanged. The protected file is deliberately not on the command policy's fenced list, so the
  kernel is the only thing that can refuse it;
- a connector host the step also probes is refused by the proxy (a 403 to the tunnel request),
  which never connects to it, and the refusal does not fail the step;
- where the backend confines the network, a request that bypasses the proxy fails.

Needs Claude Code logged in. Where the `claude` program is missing, or no sandbox backend here
confines the process, the test is held (skipped), not failed; an account that is not logged in
fails it, as in the kit's other claude_code live tests. Bills on demand, so it is marked e2e-test
and excluded from the default suite.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from agent_build_kit import claude_account, config, profiles, sandboxes
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.claude_code import API_HOST, ClaudeCodeRuntime, spawn
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.sandboxes.policy import build_policy
from tests.factories import git, init_repo

pytestmark = [pytest.mark.local_stack, pytest.mark.runtime_claude_code]

CLAUDE_ONLY_REASONS = {
    "test_a_real_claude_step_is_confined_and_reaches_the_model_only_through_the_proxy": (
        "the group confines Claude Code's process; the protocol runtime's confinement is "
        "the sandbox-acp change's"
    ),
}

ORIGINAL = "repos: {}\n"
ALLOWED_CONTENT = "allowed write\n"
REFUSED_HOST = "example.com"
DONE = "PROBE-DONE"

PROMPT = """\
This is a sandbox probe. Use the Bash tool for every step, in order, run each command exactly as
written, and keep going when one fails. Do not retry or work around a failure.

1. Run: printf 'allowed write\\n' > allowed.txt
2. Run: printf 'changed\\n' 2> denied.txt >> {protected} ; echo $? > denied.status
3. Run: curl -sS -m 20 -o /dev/null https://{refused}/ 2> curl.txt ; echo $? > curl.status
4. Run: curl -sS --noproxy '*' -m 10 -o /dev/null https://{model}/ 2> direct.txt ;
   echo $? > direct.status
5. Finish with one line that starts with {done}.
"""


@pytest.fixture
def claude_program() -> str:
    """The `claude` program, or the test is held where it is not on this host."""
    program = shutil.which("claude")
    if program is None:
        pytest.skip("claude is not on PATH: the kit's runtime: claude_code e2e is not available")
    return program


@pytest.fixture
def connected_hosts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The hosts the proxy opened a connection to, read at its upstream boundary."""
    seen: list[str] = []
    connect = socket.create_connection

    def recording(address: tuple[str, int], *args: object, **kwargs: object) -> socket.socket:
        seen.append(address[0])
        return connect(address, *args, **kwargs)  # pyrefly: ignore

    monkeypatch.setattr(socket, "create_connection", recording)
    return seen


@pytest.fixture(scope="module")
def account() -> claude_account.Account | None:
    """The account the environment names, read before the autouse fixture removes it from each
    test, as the kit's other claude_code live tests do; None for the default account."""
    for name in claude_account.NAMES:
        if os.environ.get(name):
            return claude_account.Account(
                label="probe", config_dir=Path(os.environ[name]).expanduser()
            )
    return None


class Probe:
    """A throwaway git checkout on a unit-style branch and a protected file beside it, both under
    `root`, which neither the runtime nor the profile grants."""

    def __init__(self, root: Path, account: claude_account.Account | None) -> None:
        # A checkout on a branch: the command policy reads the branch of the step's directory
        # before it allows a command at all.
        self.worktree = init_repo(root / "worktree")
        git(self.worktree, "checkout", "-q", "-b", "spec/probe/1")
        self.allowed = self.worktree / "allowed.txt"
        plan = root / "plan"
        plan.mkdir()
        self.protected = plan / config.OVERLAY_FILENAME
        self.protected.write_text(ORIGINAL)
        (plan / config.CONFIG_FILENAME).write_text(yaml.safe_dump(CONFIG))
        self.account = account
        self.installation = Installation(WorkspaceConfig.model_validate(CONFIG), plan)

    def evidence(self, name: str) -> str:
        return (self.worktree / name).read_text()

    def request(self) -> AgentRequest:
        repo = self.installation.config.repos["app"]
        policy = build_policy(
            self.installation,
            "app",
            self.worktree,
            runtime=ClaudeCodeRuntime(),
            profile=profiles.get(repo.profile),
            account=self.account,
        )
        return AgentRequest(
            prompt=PROMPT.format(
                protected=self.protected, refused=REFUSED_HOST, model=API_HOST, done=DONE
            ),
            role="implement",
            cwd=self.worktree,
            allowed_tools="Bash",
            permission_mode="edit",
            policy=ToolPolicy(sandbox=policy),
            account=self.account,
        )


# An installation that only turns the sandbox on: no lists of its own, so whatever a step needs
# beyond that comes from the kit's built-ins, the runtime and the profile, and a gap shows here.
CONFIG = {
    "repos": {
        "app": {"path": ".", "slug": "example/app", "sandbox": {"required": "process"}},
    },
}


@pytest.fixture
def probe(claude_program: str, account: claude_account.Account | None) -> Iterator[Probe]:
    backend, found = sandboxes.probe(WorkspaceConfig().sandbox.backend)
    if not found.ok:
        pytest.skip(f"{backend.name} not usable here: {found.cause} ({found.fix})")
    if not found.coverage.reaches(Coverage.PROCESS):
        pytest.skip(f"{backend.name} confines {found.coverage.value} only: {found.cause}")
    config.activate(WorkspaceConfig.model_validate(CONFIG))
    # The step may write the temp folder, so the worktree and the planning repo's stand-in are
    # kept outside it: a write to the worktree succeeds only because the policy grants it.
    root = Path(tempfile.mkdtemp(prefix="abk-probe-", dir=Path.home()))
    try:
        yield Probe(root, account)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_real_claude_step_is_confined_and_reaches_the_model_only_through_the_proxy(
    probe: Probe, connected_hosts: list[str]
) -> None:
    result = ClaudeCodeRuntime(execute=spawn).run(probe.request())

    assert result.ok, result.error
    assert DONE in result.text, result.text
    assert probe.allowed.read_text() == ALLOWED_CONTENT
    # The write to the protected file: refused by the kernel, with a permission error.
    assert probe.evidence("denied.status").strip() != "0"
    refusal = probe.evidence("denied.txt")
    assert any(m in refusal for m in ("Permission denied", "Operation not permitted")), refusal
    assert probe.protected.read_text() == ORIGINAL, "the confined step changed the protected file"
    # The connector host: the proxy answers the tunnel request with a 403 and never connects.
    assert probe.evidence("curl.status").strip() != "0"
    assert "403" in probe.evidence("curl.txt")
    assert REFUSED_HOST not in connected_hosts, connected_hosts
    assert API_HOST in connected_hosts, connected_hosts
    # A request that bypasses the proxy fails: the backend confines the network.
    assert probe.evidence("direct.status").strip() != "0", probe.evidence("direct.txt")
