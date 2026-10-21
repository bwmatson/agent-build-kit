"""No call site builds a command line holding its prompt: each reaches the runtime's executor
with the prompt as the input and none in the argument list (spec: prompt-delivery)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.pipeline.restack import claude_resolver
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT, build_run_review
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, refresh_login
from agent_build_kit.tracks import runner
from tests.conftest import make_installation
from tests.factories import activate_with
from tests.tracks.test_runner import described_installation, project


class Recording:
    """An executor that records what each call was given and answers `reply`."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path | None = None, input: str | None = None, **kwargs
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), input))
        return subprocess.CompletedProcess(argv, 0, self.reply, "")

    @property
    def runtime(self) -> ClaudeCodeRuntime:
        return ClaudeCodeRuntime(execute=self)

    def assert_carried(self, prompt: str) -> None:
        ((argv, given),) = self.calls
        assert given == prompt
        assert not any(prompt in arg for arg in argv)


def test_a_restack_resolution_carries_its_prompt_as_input(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning")
    executor = Recording()

    claude_resolver("Resolve the conflicts in a.py.", cwd=tmp_path, runtime=executor.runtime)

    executor.assert_carried("Resolve the conflicts in a.py.")


def test_a_review_carries_its_prompt_as_input(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning")
    activate_with(review={"brief": False})
    executor = Recording(reply='{"approved": true}')

    build_run_review(runtime=executor.runtime)(cwd=tmp_path)

    executor.assert_carried(REVIEW_PROMPT)


def test_a_track_phase_carries_its_prompt_as_input(tmp_path: Path) -> None:
    inst = described_installation(tmp_path / "planning", tracks={"model": "haiku"})
    executor = Recording(reply=json.dumps({"type": "result", "subtype": "success", "result": "ok"}))

    runner.claude_phase(inst, project=project(inst), name="health", runtime=executor.runtime)

    ((_, given),) = executor.calls
    assert given
    executor.assert_carried(given)


def test_the_planner_request_carries_its_prompt_as_input(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning")
    executor = Recording(reply=json.dumps({"units": [], "joins": []}))

    plan_round(
        changes={"add-marker": "## 1. [app] [unit-test] Do it\n"},
        in_flight=[],
        runtime=executor.runtime,
    )

    ((_, given),) = executor.calls
    assert given
    assert "add-marker" in given
    executor.assert_carried(given)


def test_the_login_refresh_keeps_its_fixed_prompt_as_an_argument() -> None:
    calls: list[tuple[list[str], dict]] = []

    def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    refresh_login(run=run)

    ((argv, kwargs),) = calls
    assert argv[argv.index("-p") + 1] == "Reply with OK and nothing else."
    assert "input" not in kwargs
