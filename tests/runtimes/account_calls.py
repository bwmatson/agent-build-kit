"""Each kind of `claude` call the Claude Code runtime starts, made over a fake that records the
environment it was handed, for the tests of the account variable.

A kind is a function of the test's directory returning the `env` its one call recorded: `None`
when the call was handed none.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.init.research import research
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, through
from agent_build_kit.settings import settings
from agent_build_kit.tracks import runner
from tests.pipeline.test_planner_runtime import CHANGES, PLAN
from tests.runtimes.claude_cli import FakeClaude, finished_build, record
from tests.tracks.test_runner import described_installation, project

VARIABLE = "CLAUDE_CONFIG_DIR"


def use_account(monkeypatch: pytest.MonkeyPatch, directory: Path | None) -> None:
    """The setting as the settings layer holds it: `directory`, or unset."""
    monkeypatch.setattr(settings, "claude_home", directory)


def build(tmp_path: Path) -> dict[str, str] | None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "Done."))
    ClaudeCodeRuntime(execute=fake).run(AgentRequest(prompt="Go.", role="implement", cwd=tmp_path))
    return fake.envs[0]


def planner(tmp_path: Path) -> dict[str, str] | None:
    fake = FakeClaude(stdout=json.dumps(PLAN))
    plan_round(changes=CHANGES, in_flight=[], runtime=ClaudeCodeRuntime(execute=fake))
    return fake.envs[0]


def restack_resolution(tmp_path: Path) -> dict[str, str] | None:
    fake = FakeClaude(stdout="Resolved both conflicts.")
    restack.claude_resolver("Resolve.", cwd=tmp_path, runtime=ClaudeCodeRuntime(execute=fake))
    return fake.envs[0]


def track_phase(tmp_path: Path) -> dict[str, str] | None:
    account = settings.claude_home
    inst = described_installation(tmp_path / "planning")
    # Building the installation reloads the settings, which would undo the account.
    settings.claude_home = account
    fake = FakeClaude(stdout=record("Wrote one change."))
    runner.propose(inst, project(inst), runtime=ClaudeCodeRuntime(execute=fake))
    return fake.envs[0]


def init_research(tmp_path: Path) -> dict[str, str] | None:
    """Through `through(run)`, the init steps' injection point: `run` is told the environment
    only when there is one to tell."""
    seen: list[dict[str, str] | None] = []

    def run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None):
        seen.append(env)
        return subprocess.CompletedProcess(argv, 0, "# Rules\n\nSources: none.\n", "")

    research("python", built_in=None, output=tmp_path / "python.md", runtime=through(run))
    return seen[0]


KINDS: dict[str, Callable[[Path], dict[str, str] | None]] = {
    "build": build,
    "planner": planner,
    "restack": restack_resolution,
    "track": track_phase,
    "init research": init_research,
}
