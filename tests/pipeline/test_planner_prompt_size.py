"""A planner prompt over the safe size fails as a planning failure that names its parts, and
one under it is sent whole (spec: planner-in-flight)."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.pipeline.planner import PlannerError, plan_round
from agent_build_kit.runtimes.base import PromptTransport
from tests.cli.replan_driver import answer, planned
from tests.runtimes.stand_in import StandInRuntime

PARTS = ("template", r"tasks\.md", "relationships", "calibration", "in-flight")
TASKS = "# Tasks\n\n## 1. [app] [tier1] Group one\n\n- [ ] 1.1 Test: it.\n"


def sized(size: int) -> tuple[StandInRuntime, str]:
    """A stand-in on `stdin`, and a tasks text that makes the prompt exactly `size` bytes."""
    runtime = StandInRuntime(answer=answer(planned("feature/1", (1,))))
    runtime.prompt_transport = PromptTransport.STDIN
    plan_round(changes={"feature": TASKS}, in_flight=[], runtime=runtime)
    bare = len(runtime.requests.pop().prompt.encode())
    return runtime, TASKS + "x" * (size - bare)


def test_an_oversize_prompt_names_its_parts_and_a_large_one_that_fits_is_sent_whole() -> None:
    runtime, too_large = sized(2_000_001)

    with pytest.raises(PlannerError) as refused:
        plan_round(changes={"feature": too_large}, in_flight=[], runtime=runtime)

    first, *parts = str(refused.value).splitlines()
    assert "feature" in first
    assert re.search(r"2,?000,?001", first)
    assert re.search(r"2,?000,?000", first)
    for part in PARTS:
        assert any(re.search(part, line) and re.search(r"\d", line) for line in parts), part
    assert runtime.requests == []

    runtime, large = sized(300_000)
    plan = plan_round(changes={"feature": large}, in_flight=[], runtime=runtime)

    assert len(runtime.request.prompt.encode()) == 300_000
    assert [unit.id for unit in plan.units] == ["feature/1"]
