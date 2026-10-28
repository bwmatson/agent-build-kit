"""The agent step carries the sandbox policy when `sandbox.enabled` is set, and none otherwise
(spec: sandbox-claude-code)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config import models
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.sandboxes import Coverage
from tests.factories import init_repo


class Recording(ClaudeCodeRuntime):
    """The Claude Code runtime's own sandbox entries, answering without a process."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[AgentRequest] = []

    def sandbox_paths(self, account=None) -> dict[str, list[str]]:
        # The planning repo here sits under the temp folder, and a grant of that whole folder
        # would reach `abk.yaml`: the refusal is the policy's, and its own test is below.
        given = super().sandbox_paths(account)
        return given | {"write": [path for path in given["write"] if path != "/tmp"]}

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return AgentResult(ok=True, text="built")


def install(
    tmp_path: Path,
    *,
    enabled: bool,
    required: str = "process",
    command: list[str] | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / "plan"
    main = init_repo(tmp_path / "main")
    root.mkdir()
    document: dict[str, Any] = {
        "repos": {
            "app": {
                "path": str(main),
                "slug": "example/app",
                "sandbox": {"required": required},
            }
        },
    }
    if command is not None:
        document["runtimes"] = {"claude_code": {"command": command}}
    # Written either way: the default is on, so `enabled=False` has to say so.
    document["sandbox"] = {"enabled": enabled}
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    load_installation(root / "abk.yaml").activate()
    return root, main


def step(root: Path, main: Path, runtime: Recording | None = None) -> AgentRequest:
    runtime = runtime or Recording()
    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app")(
        "Go.", cwd=main, model=models().implement
    )
    (request,) = runtime.requests
    return request


def test_with_the_sandbox_on_the_step_carries_the_repo_s_policy(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main)

    assert request.policy is not None and request.policy.sandbox is not None
    policy = request.policy.sandbox
    assert main.resolve() in policy.write
    assert Path(request.env["ABK_OUT"]).resolve() in policy.write
    assert "api.anthropic.com" in policy.hosts
    assert policy.required is Coverage.PROCESS


def test_with_the_sandbox_off_the_step_carries_no_policy(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=False)

    request = step(root, main)

    assert request.policy is not None
    assert request.policy.sandbox is None


def test_a_grant_the_policy_refuses_fails_the_step_naming_it(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)
    document = yaml.safe_load((root / "abk.yaml").read_text())
    document["repos"]["app"]["sandbox"]["write"] = [str(root / "abk.yaml")]
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    load_installation(root / "abk.yaml").activate()

    with pytest.raises(RuntimeError, match="abk.yaml"):
        step(root, main)


class Unconfining(Recording):
    sandbox_coverage = Coverage.NONE


@pytest.mark.parametrize(
    ("runtime", "said"), [(Unconfining(), True), (Recording(), False)], ids=["none", "process"]
)
def test_a_runtime_that_confines_less_than_required_says_the_step_is_unconfined(
    tmp_path: Path, runtime: Recording, said: bool
) -> None:
    root, main = install(tmp_path, enabled=True)
    lines: list[str] = []

    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app", log=lines.append)(
        "Go.", cwd=main, model=models().implement
    )

    warnings = [line for line in lines if "unconfined" in line and "process" in line]
    assert bool(warnings) is said
