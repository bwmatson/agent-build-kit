"""A `Needs:` line added to a unit that has started is an ordinary dependency.

A held unit whose thread is left where it stopped is requeued while the parent is not
yet through review: it waits as `planned` with the cause `gated`, and the pass resumes it
once the parent is in review (same repo) or has merged (other repo), restacked onto the
parent's branch. The line is linked as every tick links it; the thread is the real one.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED
from tests.factories import new_unit
from tests.tick_driver import UNIT, Setup


def held_then_needing(graph: Setup, *, repo: str = "app") -> None:
    """The unit is built and held with its thread kept; then its group gains a `Needs:`
    on `parent group 1`, a planned unit of `repo`, and the line is linked."""
    graph.tick()
    assert graph.poll(("hold", {})) == [True]
    assert graph.store.get(UNIT).state == HELD
    graph.store.upsert([new_unit("parent/1", repo=repo)])
    graph.need_parent()
    assert graph.store.get(UNIT).depends_on == ("parent/1",)


def requeue(graph: Setup) -> int:
    args = argparse.Namespace(unit=UNIT, rework=False, restart=False)
    return cli.cmd_requeue(args, graph.inst)


def test_a_held_unit_requeued_before_its_parent_is_reviewed_waits_with_its_work_kept(
    graph: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    held_then_needing(graph)
    kept = graph.store.get(UNIT)
    built = len(graph.recorder.prompts)
    capsys.readouterr()

    assert requeue(graph) == 0

    after = graph.store.get(UNIT)
    assert (after.state, after.cause) == (PLANNED, Cause.GATED)
    assert (after.branch, after.feedback) == (kept.branch, kept.feedback)
    assert graph.next() == (Node.HELD,), "the thread is left where it stopped"
    assert len(graph.recorder.prompts) == built, "no agent ran"
    assert "parent group 1" in capsys.readouterr().out


def test_the_pass_resumes_the_gated_unit_restacked_onto_the_parents_branch_once_it_is_reviewed(
    graph: Setup,
) -> None:
    held_then_needing(graph)
    graph.store.set_state("parent/1", HELD, branch="spec/parent/1")
    assert requeue(graph) == 0
    assert graph.store.get(UNIT).cause is Cause.GATED
    restacked: list[dict[str, Any]] = []
    pr_bases: list[str] = []

    def open_pr(unit: Any, *, base: str, **kw: Any) -> int:
        pr_bases.append(base)
        return graph.recorder.open_pr(unit, base=base, **kw)

    graph.options["restack_onto"] = lambda **kw: restacked.append(kw)
    graph.options["open_pr"] = open_pr

    assert graph.tick() == 0
    assert graph.store.get(UNIT).state == PLANNED, "the parent is held, not reviewed"

    graph.store.set_state("parent/1", IN_REVIEW, branch="spec/parent/1", pr=9)
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.next() == (Node.AWAIT_REVIEW,)
    assert any(str(call["base"]).endswith("spec/parent/1") for call in restacked)
    assert pr_bases[-1] == "spec/parent/1", "its pull request is updated onto the parent's branch"


def test_a_cross_repo_parent_in_review_still_holds_the_unit_until_it_has_merged(
    graph: Setup,
) -> None:
    held_then_needing(graph, repo="platform")
    graph.store.set_state("parent/1", IN_REVIEW, branch="spec/parent/1", pr=9)

    assert requeue(graph) == 0
    assert graph.store.get(UNIT).cause is Cause.GATED
    assert graph.tick() == 0
    assert graph.store.get(UNIT).state == PLANNED
    assert graph.next() == (Node.HELD,)

    graph.store.set_state("parent/1", MERGED, pr=9)
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW


def test_status_lists_the_gated_unit_as_waiting_on_the_parents_group(
    graph: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    held_then_needing(graph)
    assert requeue(graph) == 0
    capsys.readouterr()

    assert cli.cmd_status(argparse.Namespace(), graph.inst) == 0

    lines = capsys.readouterr().out.splitlines()
    waiting = next(line for line in lines if UNIT in line and "waiting" in line)
    assert "parent group 1" in waiting
