"""A rework call is labelled `rework`, not `implement` (spec: roles, a rework call)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.gateway_usage import attribution
from agent_build_kit.pipeline.wiring import build_run
from tests.call_rows import Spending
from tests.graph.test_build_path import fresh
from tests.graph_driver import tick
from tests.leftovers_driver import step_of
from tests.runner_fakes import approving, rejecting
from tests.runtimes.stand_in import StandInRuntime


def test_the_agent_run_that_answers_review_is_a_rework_call(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("name it better"), approving()]
    runtime = StandInRuntime(answer=recorder.rework_answer)
    agent = build_run(runtime=runtime, planning_repo=tmp_path / "meta")

    def run(prompt: str, **kwargs: Any) -> str:
        return agent(prompt, **kwargs)

    tick(tmp_path, recorder, run=run)

    answering = [r.role for r in runtime.requests if step_of(r.prompt) == "rework"]
    building = [r.role for r in runtime.requests if step_of(r.prompt) != "rework"]
    assert answering == ["rework"]
    assert set(building) == {"implement"}


def test_a_build_call_under_the_adapt_node_is_a_rework_call(tmp_path: Path) -> None:
    runtime = Spending()
    recorded: list[str] = []
    agent = build_run(runtime=runtime, planning_repo=tmp_path / "meta")

    token = attribution.set("feature/1:adapt:1")
    try:
        agent(
            "Adapt it.",
            cwd=tmp_path,
            on_result=lambda result, **row: recorded.append(row["role"]),
        )
    finally:
        attribution.reset(token)

    assert runtime.requests[-1].role == "rework"
    assert recorded == ["rework"]
