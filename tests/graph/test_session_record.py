"""A completed agent node leaves its role's session in the unit's state, whether or not
anything reuses it (docs/unit-graph.md, Session capture and resume)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.graph.state import Node, SessionRole
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.graph.agent_fakes import MODELS, Reviews, Runs, distinct_models
from tests.graph.test_build_path import FAILING, build, once, restacked
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Killed, rejecting
from tests.runtimes.claude_cli import SESSION, FakeClaude, finished_build


def test_the_build_and_review_sessions_are_each_recorded_under_their_role(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, run=Runs(recorder), run_review=Reviews(recorder))

    state = position(tmp_path).state
    assert state is not None
    assert set(state.sessions) == {SessionRole.BUILD, SessionRole.REVIEW}
    built, judged = state.sessions[SessionRole.BUILD], state.sessions[SessionRole.REVIEW]
    assert (built.session_id, built.node) == ("sess-2", Node.IMPLEMENT)
    assert (built.runtime, built.model) == ("fake", MODELS.implement)
    assert (judged.session_id, judged.node) == ("rev-1", Node.REVIEW)


def test_fix_checks_updates_the_build_session_and_leaves_the_review_one(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]
    recorder.tier1_results = [(True, ""), (False, FAILING), (True, "")]
    runs = Runs(recorder)
    # The second review is where the power goes, after fix_checks has completed.
    reviews = Reviews(recorder, kill_on=2)

    with pytest.raises(Killed):
        tick(tmp_path, recorder, run=runs, run_review=reviews, run_rework_review=reviews)

    state = position(tmp_path).state
    assert state is not None
    built = state.sessions[SessionRole.BUILD]
    assert (built.node, built.session_id) == (Node.FIX_CHECKS, f"sess-{len(runs.calls)}")
    judged = state.sessions[SessionRole.REVIEW]
    assert (judged.node, judged.session_id) == (Node.REVIEW, "rev-1")


def test_build_model_is_the_first_build_nodes_and_a_later_node_leaves_it(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]
    runs = Runs(recorder)

    tick(tmp_path, recorder, run=runs)

    *_, rework = runs.calls
    assert rework.model == MODELS.rework, "a later build node runs on another model"
    state = position(tmp_path).state
    assert state is not None
    assert state.build_model == MODELS.implement


def test_a_unit_entering_at_adapt_has_its_build_model_from_adapt(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        run=Runs(recorder),
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=once(restacked(conflict="x", old_tests=())),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
    )

    state = position(tmp_path).state
    assert state is not None
    assert state.build_model == MODELS.rework
    assert state.sessions[SessionRole.BUILD].node == Node.ADAPT


def test_the_real_build_run_leaves_the_stream_session_with_its_runtime_and_model(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    run = build_run(
        runtime=ClaudeCodeRuntime(execute=FakeClaude(stdout=finished_build(tmp_path, "done")))
    )

    tick(tmp_path, recorder, run=run)

    state = position(tmp_path).state
    assert state is not None
    built = state.sessions[SessionRole.BUILD]
    assert (built.session_id, built.runtime, built.model) == (
        SESSION,
        "claude_code",
        models().implement,
    )
