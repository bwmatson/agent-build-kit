"""A rework call is labelled `rework`, not `implement` (spec: roles, a rework call)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.wiring import build_run
from tests.graph.test_build_path import fresh
from tests.graph_driver import tick
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

    # The recorder's own way of telling a rework's prompt from the build's.
    def reworking(prompt: str) -> bool:
        return "review of this branch" in prompt or "Review asked for" in prompt

    answering = [r.role for r in runtime.requests if reworking(r.prompt)]
    building = [r.role for r in runtime.requests if not reworking(r.prompt)]
    assert answering == ["rework"]
    assert set(building) == {"implement"}
