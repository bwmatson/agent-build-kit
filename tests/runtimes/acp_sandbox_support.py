"""What the ACP sandbox tests share: a scene (a worktree a confined terminal may write, a protected
file it may not, a secret folder the read list leaves out), the real backend wrapped to see what it
was asked, and the fixtures that put both in place."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import agent_build_kit
from agent_build_kit.runtimes import AgentRequest, AgentResult, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.sandboxes import Coverage, SandboxBackend, SandboxPolicy
from tests.runtimes.acp_agent import command, requests, use_command
from tests.sandboxes.landlock_support import readable_folders

SECRETS = {
    "ABK_GATEWAY_MASTER_KEY": "gateway-secret",
    "ABK_GRAFANA_TOKEN": "grafana-secret",
    "AZURE_DEVOPS_EXT_PAT": "ado-secret",
}
PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")
KIT = Path(agent_build_kit.__file__).resolve().parents[2]


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
    """A worktree the confined terminal may write, a protected file it may not, and a secret
    folder the policy's read list leaves out."""

    def __init__(self, root: Path) -> None:
        self.worktree = root / "worktree"
        self.record_dir = root / "record"
        self.protected = root / "protected"
        self.secret = root / "secret"
        for folder in (self.worktree, self.record_dir, self.protected, self.secret):
            folder.mkdir()
        self.record = self.record_dir / "agent.jsonl"
        self.target = self.protected / "file.txt"
        self.target.write_text("original\n")
        self.hidden = self.secret / "token.txt"
        self.hidden.write_text("hidden\n")
        (self.worktree / "ok.txt").write_text("fine\n")
        (self.worktree / "link.txt").symlink_to(self.hidden)
        self.command: list[str] = []

    def write_only_policy(self) -> SandboxPolicy:
        """The shape `build_policy` gives a worktree: granted for writing, not listed to read."""
        policy = self.policy()
        return policy.model_copy(
            update={"read": tuple(p for p in policy.read if p != self.worktree.resolve())}
        )

    def policy(self, *, write_worktree: bool = True) -> SandboxPolicy:
        """Reads the system, the kit and the worktree; the temp folder (which holds the other
        folders of this scene) is not on the read list."""
        temp = Path(tempfile.gettempdir()).resolve()
        system = tuple(path for path in readable_folders() if path != temp)
        return SandboxPolicy(
            write=(
                *((self.worktree.resolve(),) if write_worktree else ()),
                self.record_dir.resolve(),
                Path("/dev"),
            ),
            read=(*system, KIT, self.worktree.resolve(), self.record_dir.resolve()),
            hosts=("api.example.com",),
            required=Coverage.FILES,
        )

    def act(self, *actions: dict[str, Any], watch: tuple[str, ...] = ()) -> None:
        self.command = command(self.record, act=list(actions), watch=watch)
        use_command(self.command)

    def run(self, policy: SandboxPolicy | None, *, scoped: bool = True) -> AgentResult:
        return AcpRuntime().run(
            AgentRequest(
                prompt="Go.",
                role="implement",
                cwd=self.worktree,
                policy=ToolPolicy(sandbox=policy, scoped=scoped),
            )
        )

    def terminal(self) -> dict[str, Any]:
        [ran] = requests(self.record, "did/terminal")
        return ran


def shell(line: str) -> dict[str, Any]:
    return {"terminal": "sh", "args": ["-c", line]}
