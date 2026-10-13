"""The restack's agent step runs in `prepare`, as a call of the unit's build session (spec:
restack-conflicts, the step runs under the usage gate in the run that finds the conflict;
session-reuse, a conflict resolved in the build session).

`restack_onto` is faked at its edge: it is given a `resolver` by `prepare` and calls it as
`move_branch_onto` does, once with the order and, for a second call, with `follow_up`
naming the failed check. What is asserted is what reaches the runtime, and what `verify_base`
does with a conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import Node, SessionRole
from agent_build_kit.pipeline.restack import RESOLVER_TOOLS
from agent_build_kit.pipeline.stack_runner import Restacked, RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import BASE_TOOLS
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.base import AgentRateLimited
from tests.factories import unit
from tests.graph.agent_fakes import MODELS, distinct_models
from tests.graph.test_build_path import build, restacked
from tests.graph.test_session_continuation import (
    FAILING,
    Sessions,
    agents,
    failing_checks,
    reuse,
)
from tests.graph_driver import fresh, position, tick

FIRST = "ORDER: hunks first, then dependent files, then a port. Conflicted: a.py"
SECOND = "ORDER: hunks first, then dependent files, then a port. FAILED: b.py lost make_thing"
CONTINUE = "Your resolution lost make_thing; you may now change the files that depend on a.py."
SETTLED = ("a.py", "b.py")


class Settling:
    """`restack_onto`: before a push (`resolve` false) it finds a conflict `conflicts` times;
    given a `resolver` it asks it `asks` times, as the move does, and says the move was
    settled. What it was called with is kept."""

    def __init__(self, *, conflicts: int = 1, asks: int = 2) -> None:
        self.conflicts = conflicts
        self.asks = asks
        self.seen: list[tuple[bool, bool]] = []

    def __call__(self, **kw: Any) -> Restacked | None:
        self.seen.append((kw.get("resolve", True), "resolver" in kw))
        if (resolver := kw.get("resolver")) is not None:
            resolver(FIRST, cwd=kw["tree"])
            if self.asks > 1:
                resolver(SECOND, cwd=kw["tree"], follow_up=CONTINUE)
            return restacked(resolved=SETTLED)
        if not kw.get("resolve", True) and self.conflicts:
            self.conflicts -= 1
            return restacked(conflict="CONFLICT in a.py")
        return None


class PausedFrom(Sessions):
    """A runtime whose account is out of room from request `n` on."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n

    def run(self, request: AgentRequest) -> AgentResult:
        if len(self.requests) + 1 >= self.n:
            self.requests.append(request)
            raise AgentRateLimited("usage limit reached")
        return super().run(request)


def restack_calls(runtime: Sessions) -> list[AgentRequest]:
    """The build requests after the tests' and the implementation's: the restack's calls."""
    return runtime.built[2:]


# --- the step's calls are calls of the build session -----------------------------------------


def test_with_reuse_on_both_calls_continue_the_recorded_build_session(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()
    restack = Settling()

    tick(tmp_path, recorder, restack_onto=restack, **agents(runtime))

    first, second = restack_calls(runtime)
    assert (first.resume_session, second.resume_session) == ("sess-1", "sess-1")
    assert first.model == second.model == MODELS.implement, "the session's recorded model"
    assert FIRST in first.prompt, "the order is in the first call"
    assert CONTINUE in second.prompt and SECOND not in second.prompt
    state = position(tmp_path).state
    assert state is not None
    recorded = state.sessions[SessionRole.BUILD]
    assert (recorded.node, recorded.session_id) == (Node.RESTACK, "sess-1")


def test_a_unit_whose_first_agent_call_is_the_restack_starts_the_build_session_on_rework(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()
    answers = iter([Settling(asks=1)])

    def once(**kw: Any) -> Restacked | None:
        found = next(answers, None)
        return found(**kw) if found is not None else None

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=once,
        **agents(runtime),
    )

    restack, fix = runtime.built
    assert restack.resume_session == ""
    assert restack.model == MODELS.rework
    assert FIRST in restack.prompt
    assert fix.resume_session == "sess-1", "the next build node continues it"
    assert fix.model == MODELS.rework
    assert FAILING in fix.prompt


def test_with_reuse_off_each_call_is_a_new_session_whose_prompt_repeats_the_order(
    tmp_path: Path,
) -> None:
    distinct_models()
    reuse(build=False)
    recorder = fresh(tmp_path)
    runtime = Sessions()

    build(tmp_path, recorder, restack_onto=Settling(), **agents(runtime))

    first, second = restack_calls(runtime)[:2]
    assert (first.resume_session, second.resume_session) == ("", "")
    assert first.model == second.model == MODELS.rework
    assert SECOND in second.prompt, "the order and the failed check, in full"
    assert CONTINUE not in second.prompt


def test_a_session_the_runtime_cannot_continue_runs_the_call_in_a_new_one_with_the_full_prompt(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions(refuses="the session is gone")

    outcome = build(tmp_path, recorder, restack_onto=Settling(), **agents(runtime))

    last = restack_calls(runtime)[-1]
    assert last.resume_session == ""
    assert SECOND in last.prompt
    assert outcome.status == "open", "not an error"


# --- where the step runs ---------------------------------------------------------------------


def test_a_conflict_found_before_a_push_is_settled_in_the_same_run_by_prepare(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()
    restack = Settling()

    outcome = build(tmp_path, recorder, restack_onto=restack, **agents(runtime))

    assert outcome.status == "open"
    assert restack.seen == [(False, False), (True, True), (False, False)], (
        "verify_base asks without a resolver, prepare asks with one, and the settled move "
        "is not a second conflict"
    )
    assert len(restack_calls(runtime)) == 2, "and only prepare's step made agent calls"


def test_a_second_conflict_in_the_run_leaves_the_unit_planned_for_a_later_tick(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    runtime = Sessions()
    restack = Settling(conflicts=2)

    outcome = build(tmp_path, recorder, restack_onto=restack, **agents(runtime))

    stored = recorder.store.get(unit().id)
    assert outcome.status == "held"
    assert (stored.state, stored.cause) == (PLANNED, Cause.BASE_CHANGED)
    assert "push" not in recorder.events
    assert len(restack_calls(runtime)) == 2, "the first conflict was settled, not the second"


def test_a_usage_pause_defers_the_step_and_the_unit_is_not_failed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    runtime = PausedFrom(4)  # the tests, the implementation and the review have run

    with pytest.raises(AgentRateLimited):
        build(tmp_path, recorder, restack_onto=Settling(asks=1), **agents(runtime))

    stored = recorder.store.get(unit().id)
    assert stored.state != "failed"
    assert "conflict" not in stored.feedback
    assert "push" not in recorder.events


def test_a_clean_move_in_a_usage_pause_is_made_and_the_unit_waits_at_the_next_gate(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    runtime = Sessions()
    moves: list[dict[str, Any]] = []

    def clean(**kw: Any) -> Restacked | None:
        moves.append(kw)
        return restacked()

    outcome = tick(
        tmp_path,
        recorder,
        branch_commits=lambda cwd, base: 2,
        restack_onto=clean,
        may_start=lambda: (False, "session usage at 88%"),
        resume_at=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        **agents(runtime),
    )

    assert len(moves) == 1 and moves[0]["resolver"] is not None, "the move was made"
    assert runtime.requests == [], "and asked no agent"
    assert outcome.status == RunStatus.PAUSED, "the unit waits at the next agent node's gate"
    stored = recorder.store.get(unit().id)
    assert stored.state != "failed"
    assert stored.cause != Cause.RESTACK_CONFLICT


def test_the_resolution_calls_carry_the_resolvers_tools_and_the_next_build_node_the_builds(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()
    answers = iter([Settling(asks=2)])

    def once(**kw: Any) -> Restacked | None:
        found = next(answers, None)
        return found(**kw) if found is not None else None

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=once,
        **agents(runtime),
    )

    first, second, fix = runtime.built
    for request in (first, second):
        assert request.allowed_tools == RESOLVER_TOOLS
        assert request.permission_mode == "allowed_tools_only"
    assert fix.allowed_tools == BASE_TOOLS
    assert fix.permission_mode == "edit"
