"""A `Needs:` line that arrives while a unit is building, in review or sent back.

The build's own checks (`build_upstream_incomplete`, `build_base_moved`) read the store
between steps, so the line is felt there; an in-review unit is left alone until it is
sent back, and then waits for the parent and restacks onto it.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, UnitState
from agent_build_kit.pipeline.wiring import build_base_moved, build_upstream_incomplete
from tests.factories import new_unit
from tests.tick_driver import UNIT, Setup


def real_checks(graph: Setup) -> None:
    graph.options["upstream_incomplete"] = build_upstream_incomplete(graph.store)
    graph.options["base_moved"] = build_base_moved(graph.store)


def recording_restacks(graph: Setup) -> list[str]:
    bases: list[str] = []
    graph.options["restack_onto"] = lambda **kw: bases.append(str(kw["base"]))
    return bases


@pytest.mark.parametrize(
    ("parent_state", "cause"),
    [(HELD, Cause.UPSTREAM_WENT_BACK), (IN_REVIEW, Cause.BASE_CHANGED)],
)
def test_a_running_unit_finishes_its_step_then_stops_and_resumes_onto_the_parent(
    graph: Setup,
    capsys: pytest.CaptureFixture[str],
    parent_state: UnitState,
    cause: Cause,
) -> None:
    graph.store.upsert([new_unit("parent/1")])
    graph.store.set_state("parent/1", parent_state, branch="spec/parent/1", pr=9)
    real_checks(graph)
    bases = recording_restacks(graph)
    steps: list[str] = []

    def agent(prompt: str, **kw: Any) -> str:
        if not steps:
            graph.need_parent()
        steps.append(prompt)
        return graph.recorder.claude(prompt, **kw)

    graph.options["run"] = agent

    assert graph.tick() == 0

    stopped = graph.store.get(UNIT)
    assert steps, "the step in progress ran to its end"
    assert cause.value in [entry.get("cause") for entry in stopped.history], "it stopped"
    if parent_state == HELD:
        assert stopped.state == PLANNED
    assert graph.tick() == 0
    assert capsys.readouterr().out.count("now depends on parent/1") == 1

    graph.store.set_state("parent/1", IN_REVIEW, branch="spec/parent/1", pr=9)
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert any(base.endswith("spec/parent/1") for base in bases)


def test_an_in_review_unit_is_not_moved_when_a_needs_line_is_added(graph: Setup) -> None:
    graph.tick()
    graph.store.upsert([new_unit("parent/1")])
    graph.store.set_state("parent/1", HELD, branch="spec/parent/1")
    before = graph.store.get(UNIT)
    bases = recording_restacks(graph)
    pr_calls = graph.recorder.pr_calls

    graph.need_parent()
    assert graph.tick() == 0

    after = graph.store.get(UNIT)
    assert (after.state, after.pr, after.branch, after.pushed) == (
        IN_REVIEW,
        before.pr,
        before.branch,
        before.pushed,
    )
    assert graph.next() == (Node.AWAIT_REVIEW,)
    assert bases == [] and graph.recorder.pr_calls == pr_calls


def test_a_unit_sent_back_while_its_parent_is_not_reviewed_waits_then_restacks_onto_it(
    graph: Setup,
) -> None:
    graph.tick()
    graph.store.upsert([new_unit("parent/1")])
    graph.store.set_state("parent/1", HELD, branch="spec/parent/1")
    graph.need_parent()
    real_checks(graph)
    bases = recording_restacks(graph)
    pr_bases: list[str] = []

    def open_pr(unit: Any, *, base: str, **kw: Any) -> int:
        pr_bases.append(base)
        return graph.recorder.open_pr(unit, base=base, **kw)

    graph.options["open_pr"] = open_pr
    built = len(graph.recorder.prompts)

    assert graph.poll(("rework", {"reason": "new comment"})) == [True]
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == PLANNED
    assert len(graph.recorder.prompts) == built, "not started while the parent is held"

    graph.store.set_state("parent/1", IN_REVIEW, branch="spec/parent/1", pr=9)
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert any(base.endswith("spec/parent/1") for base in bases)
    assert pr_bases[-1] == "spec/parent/1"
