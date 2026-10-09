"""Every node that runs an agent runs on a runtime that names no models.

The ACP runtime declares an empty name for every role, so a node reaches the run
entry point with no model and the agent runs on its own default. The entry point
is the real `build_run` closure, over the real `AcpRuntime` and the recorded
agent: a fake of the entry point declares the model itself and would hide it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit import config
from agent_build_kit.config import models
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import Adapting, decisions
from tests.graph_driver import fresh, position, tick
from tests.leftovers_driver import Habitat, Hands, step_of
from tests.runner_fakes import rejecting
from tests.runtimes.acp_agent import DEFAULT_MODEL, MODEL_AT_PROMPT, requests, use_agent
from tests.runtimes.stand_in import StandInRuntime


class WritingAcp(AcpRuntime):
    """The real ACP runtime, after the edit the agent would make: the worktree
    needs a change for the node's commit to take."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.asked.append(request)
        if request.cwd is not None and request.cwd.is_dir():
            (request.cwd / f"edit-{len(self.asked)}.txt").write_text("done\n")
        return super().run(request)


def on_acp(tmp_path: Path, **agent: Any) -> tuple[Path, WritingAcp]:
    """The active workspace on the ACP runtime, every role empty, and the agent it runs."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, **agent)
    current = config.active()
    config.activate(current.model_copy(update={"runtime": "acp"}), config.active_root())
    assert models().implement == models().rework == models().review == ""
    return record, WritingAcp()


def habitat_on(tmp_path: Path, runtime: Any) -> Habitat:
    habitat = Habitat(tmp_path, Hands())
    habitat.runtime = runtime
    return habitat


def steps(runtime: WritingAcp) -> list[str]:
    return [step_of(request.prompt) for request in runtime.asked]


def selected_nothing(record: Path, runtime: WritingAcp) -> None:
    assert runtime.asked, "the agent was reached"
    assert all(not request.model for request in runtime.asked)
    chosen = requests(record, "session/set_config_option")
    assert [c for c in chosen if c["configId"] == "model"] == []
    at_prompt = requests(record, MODEL_AT_PROMPT)
    assert len(at_prompt) == len(runtime.asked)
    assert [p["model"] for p in at_prompt] == [DEFAULT_MODEL] * len(at_prompt)


def test_the_tests_and_implement_nodes_start_the_agent_with_no_model(tmp_path: Path) -> None:
    record, runtime = on_acp(tmp_path)
    habitat = habitat_on(tmp_path, runtime)

    outcome = tick(tmp_path, fresh(tmp_path), **habitat.overrides())

    assert outcome.status == RunStatus.OPEN
    assert steps(runtime) == ["tests", "implement"]
    selected_nothing(record, runtime)


def test_the_fix_checks_node_starts_the_agent_with_no_model(tmp_path: Path) -> None:
    record, runtime = on_acp(tmp_path)
    habitat = habitat_on(tmp_path, runtime)
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, "E501 line too long")]

    outcome = tick(tmp_path, recorder, **habitat.overrides())

    assert outcome.status == RunStatus.OPEN
    assert steps(runtime) == ["tests", "implement", "fix_checks"]
    selected_nothing(record, runtime)


def test_the_rework_node_starts_the_agent_with_no_model(tmp_path: Path) -> None:
    record, runtime = on_acp(tmp_path)
    habitat = habitat_on(tmp_path, runtime)
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]

    outcome = tick(tmp_path, recorder, **habitat.overrides())

    assert outcome.status == RunStatus.OPEN
    assert steps(runtime) == ["tests", "implement", "rework"]
    selected_nothing(record, runtime)


def test_a_continued_session_reaches_the_agent_with_no_model(tmp_path: Path) -> None:
    """The rework continues the build's session, which an agent that loads one holds."""
    record, runtime = on_acp(tmp_path, load_session=True)
    habitat = habitat_on(tmp_path, runtime)
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]

    outcome = tick(tmp_path, recorder, **habitat.overrides())

    assert outcome.status == RunStatus.OPEN
    assert len(requests(record, "session/load")) == 1, "the build session was continued"
    selected_nothing(record, runtime)
    state = position(tmp_path).state
    assert state is not None and state.sessions


def test_the_adapt_node_starts_the_agent_with_no_model(tmp_path: Path) -> None:
    record, runtime = on_acp(tmp_path)
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""))],
        old_tests=("test_click",),
        present={"test_click"},
    )
    overrides = adapting.overrides()
    overrides["run"] = build_run(runtime=runtime)

    build(tmp_path, recorder, base="spec/c/2", **overrides)

    assert len(runtime.asked) == 1, "the adapt reached the runtime"
    selected_nothing(record, runtime)


def test_over_the_claude_code_runtime_a_node_runs_on_the_model_for_its_role(
    tmp_path: Path,
) -> None:
    runtime = StandInRuntime(answer="done")
    habitat = Habitat(tmp_path, Hands())
    overrides = habitat.overrides()
    run = build_run(runtime=runtime)

    def write_then_run(prompt: str, *, cwd: Path, **kw: Any) -> str:
        (cwd / f"edit-{len(runtime.requests)}.txt").write_text("done\n")
        return run(prompt, cwd=cwd, **kw)

    overrides["run"] = write_then_run
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]

    tick(tmp_path, recorder, **overrides)

    by_step = {step_of(r.prompt): r.model for r in runtime.requests}
    assert by_step["tests"] == by_step["implement"] == models().implement != ""
    assert by_step["rework"] == models().rework != ""
