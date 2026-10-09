"""The build path's nodes: `wiring.build_runner`'s callables, one step each.

A node killed partway runs again from its start (docs/unit-graph.md,
Durability), so each one first looks at what the world already holds — the
branch's tip, the pushed commit, the pull request — and does nothing twice.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.graph import END
from langgraph.types import interrupt

from agent_build_kit import forges, profiles, telemetry
from agent_build_kit.config import active, models
from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.graph.state import (
    AgentSession,
    EventKind,
    Node,
    ResumeEvent,
    SessionRole,
    UnitRun,
    Verdict,
)
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.changelog_convention import changelog_note
from agent_build_kit.pipeline.check_failures import failed_check
from agent_build_kit.pipeline.events import (
    held_cause,
    held_for_its_own_reason,
    restore_depth_hold,
    takeover_note,
)
from agent_build_kit.pipeline.gateway_usage import Spend, attribution
from agent_build_kit.pipeline.metric_records import record_metric
from agent_build_kit.pipeline.outside_commits import outside_commits_note
from agent_build_kit.pipeline.pr_body import build_pr_body, satisfied_reason
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import (
    ADAPT_CONTINUATION,
    ADAPT_FOLLOWUP_PROMPT,
    ADAPT_PROMPT,
    CHECKS_CONTINUATION,
    CHECKS_PROMPT,
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    LEFTOVERS_NOTE,
    MOVED_NOTE,
    PREDECESSOR_NOTE,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    TESTS_PROMPT,
    TIER1_FAILED,
    Escalation,
    Restacked,
    RunStatus,
    UnitOutcome,
    UnitRunner,
    check_test_decisions,
    escalates,
    parse_test_decisions,
    tests_needing_decision,
    with_response,
)
from agent_build_kit.pipeline.unit_store import (
    Cause,
    ClosePending,
    FeedbackSource,
    HeldBy,
    RequeueReason,
    StoredUnit,
)
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    SATISFIED,
    Unit,
    UnitState,
    branch_name,
    depth_of,
    local_ref,
)
from agent_build_kit.pipeline.usage_ledger import UsageRecord, record_call
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentResult,
    SessionUnavailable,
)
from agent_build_kit.usage import Usage

Update = dict[str, Any]

# What a trip back through `prepare` starts over from; the rest of the state is
# what that trip recomputes.
FRESH: Update = {
    "restack": False,
    "moved": False,
    "conflict": None,
    "verdict": None,
    "fix_rounds": 0,
    "review_round": 0,
    "spent": False,
    "checks_ok": False,
    "produced_nothing": False,
    "snapshot": "",
}

# Paths of uncommitted work named in a prompt or a hold; the rest are counted.
LEFTOVER_PATHS_SHOWN = 40

# Lines of a failing tier 2's report written to the run log.
TIER2_LOG_TAIL = 40

# The nodes a unit is held before, at the boundary, when its upstream went back
# for rework or its base moved: the ones that start work or leave the machine.
GATED = frozenset({Node.IMPLEMENT, Node.FIX_CHECKS, Node.REVIEW, Node.REWORK, Node.VERIFY_BASE})
# The nodes that start an agent: each asks the usage guard first.
AGENT_NODES = frozenset(
    {Node.TESTS, Node.IMPLEMENT, Node.FIX_CHECKS, Node.REVIEW, Node.REWORK, Node.ADAPT}
)
# The agent nodes that edit the tree: a dirty tree left by a killed run of one of
# these is that node's own work to carry on from. Review writes nothing.
EDITING_NODES = frozenset({Node.TESTS, Node.IMPLEMENT, Node.FIX_CHECKS, Node.REWORK, Node.ADAPT})
# The nodes a park records and a requeue goes back to, with their inputs as they stood:
# `prepare` would route on the branch alone and lose what the node was to do.
PARKABLE = EDITING_NODES | {Node.REVIEW}
# The conversation each agent node speaks in. A node gets a role of its own only
# when it must not share context with the others (a reviewer with the author).
SESSION_ROLES: dict[Node, SessionRole] = {
    Node.TESTS: SessionRole.BUILD,
    Node.IMPLEMENT: SessionRole.BUILD,
    Node.FIX_CHECKS: SessionRole.BUILD,
    Node.REWORK: SessionRole.BUILD,
    Node.ADAPT: SessionRole.BUILD,
    Node.REVIEW: SessionRole.REVIEW,
}
# The nodes a thread waits in, for the forge or for a person.
WAITS = frozenset({Node.AWAIT_REVIEW, Node.HELD})


def _model(model: str) -> dict[str, str]:
    """The model a call names, when it names one: a review's runner has its own."""
    return {"model": model} if model else {}


class BuildPath:
    """Runs one unit's build path, a node at a time, over `runner`'s callables."""

    def __init__(
        self,
        runner: UnitRunner,
        unit: Unit,
        *,
        base: str,
        graph: list[StoredUnit],
        run_log: RunLog | None,
        tracer: Any,
    ) -> None:
        self.runner = runner
        self.unit = unit
        self.base = base
        self.graph = graph
        self.run_log = run_log
        self.tracer = tracer
        # Told each session id a running agent reports; set by whoever drives
        # the thread, as writing it into the thread's state is theirs to do.
        self.on_session: Callable[[str], None] | None = None
        # Told the name of each agent node as it starts, likewise.
        self.on_start: Callable[[str], None] | None = None
        # When the thread's usage pause began, set by whoever resumes a paused
        # thread; the gate records the pause once the guard lets the node start.
        self.paused_since: spans.Mark | None = None
        self._tree: Path | None = None
        self._node = ""
        # Whether a dirty tree is the running node's own, killed mid-agent, and what it holds.
        self._own = False
        self._leftovers: tuple[str, ...] = ()
        # The last session an agent call of the running node ended in: (id, runtime, model).
        self._ended: tuple[str, str, str] | None = None

    def work(self) -> dict[Node, Callable[[UnitRun], Any]]:
        """Each node's body, wrapped in its span and run off the event loop."""
        bodies = {
            Node.PREPARE: self.prepare,
            Node.TESTS: self.tests,
            Node.IMPLEMENT: self.implement,
            Node.CHECKS: self.checks,
            Node.FIX_CHECKS: self.fix_checks,
            Node.REVIEW: self.review,
            Node.REWORK: self.rework,
            Node.ADAPT: self.adapt,
            Node.TIER1: self.tier1,
            Node.TIER2: self.tier2,
            Node.VERIFY_BASE: self.verify_base,
            Node.NEW_COMMENTS: self.new_comments,
            Node.PUSH: self.push,
            Node.OPEN_PR: self.open_pr,
            Node.AWAIT_REVIEW: self.await_review,
            Node.HELD: self.held,
            Node.SATISFIED: self.satisfied,
            Node.FAILED: self.failed,
        }
        return {node: self._wrapped(node, body) for node, body in bodies.items()}

    def _wrapped(self, node: Node, body: Callable[[UnitRun], Update]):
        async def run(state: UnitRun) -> Update:
            self._own = node in EDITING_NODES and state.running_node == node.value
            self._leftovers = ()
            if node in AGENT_NODES:
                await self.gate(node, state)
                if self.on_start:
                    await asyncio.to_thread(self.on_start, node.value)
            attributes: dict[str, str | int] = {
                "unit": self.unit.id,
                "change": self.unit.change,
                "step": node.value,
            }
            if round_number := _round(node, state):
                attributes["round"] = round_number
            span: AbstractContextManager[Any] = (
                self.tracer.start_as_current_span(
                    node.value, attributes=attributes, **telemetry.SPAN_OPTIONS
                )
                if self.tracer
                else nullcontext()
            )
            started = time.monotonic()
            mark = spans.Mark()
            outcome = UnitOutcome.ERROR
            with span as current:
                self._node = node.value
                self._ended = None
                context = spans.current_unit.set(
                    (self.unit.id, self.unit.change, node.value, _round(node, state))
                )
                self.say("started")
                try:
                    # Off the loop: the callables block on agents and git.
                    update = await asyncio.to_thread(self._step, node, body, state)
                    if update.get("stopped"):
                        # The run ends `failed` for this, and the record names the step.
                        self.record_step(node)
                    outcome = (
                        UnitOutcome(update["status"]) if update.get("status") else UnitOutcome.OK
                    )
                    # The node is done, and with it the session it was in.
                    done: Update = {
                        **update,
                        **self._sessions_after(node, state, update),
                        "session_id": "",
                        "running_node": "",
                    }
                    # The waiting node's own return must not clear what a requeue routes on.
                    return done if node is Node.HELD else {**done, "parked_node": ""}
                except DirtyWorktree as error:
                    outcome = UnitOutcome.HELD
                    # A node that follows a park by a fixed edge (tests to implement) parks
                    # again on the same tree: the first one is where a requeue goes back to.
                    again = bool(state.held and state.parked_node)
                    return {
                        **self.park(error),
                        "running_node": "",
                        "parked_node": state.parked_node
                        if again
                        else (node.value if node in PARKABLE else ""),
                    }
                except GraphInterrupt:
                    outcome = UnitOutcome.WAITING
                    raise
                except AgentRateLimited:
                    outcome = UnitOutcome.RATE_LIMITED
                    raise
                except AgentInterrupted:
                    outcome = UnitOutcome.INTERRUPTED
                    raise
                except BaseException as error:
                    if isinstance(error, Exception):
                        # Where it failed, for the unit's record (`abk status`).
                        # The error being handled is the one to raise.
                        self.record_step(node)
                    if current is not None:
                        telemetry.failed(current)
                    raise
                finally:
                    spans.current_unit.reset(context)
                    spans.record_span(
                        mark,
                        self.say,
                        unit=self.unit.id,
                        change=self.unit.change,
                        node=node.value,
                        round_number=_round(node, state),
                        outcome=outcome,
                    )
                    if current is not None:
                        current.set_attribute("outcome", outcome)
                    telemetry.duration(
                        "abk.step.duration",
                        time.monotonic() - started,
                        step=node.value,
                        outcome=outcome,
                    )

        return run

    def record_step(self, node: Node) -> None:
        """Name `node` as the step the unit is failing in; never raises."""
        try:
            self.runner.store.record_step(self.unit.id, node.value)
        except Exception as recording:  # noqa: BLE001
            self.say(f"could not record the failing step — {recording}")

    def _sessions_after(self, node: Node, state: UnitRun, update: Update) -> Update:
        """The role's session as the node leaves it, and the model the build began on."""
        if (role := SESSION_ROLES.get(node)) is None:
            return {}
        if self._ended is None:
            # A call killed before it reported its result leaves no session to record, and
            # the role's earlier one no longer holds what the node did.
            if state.session_id and role in state.sessions:
                return {"sessions": {k: v for k, v in state.sessions.items() if k != role}}
            return {}
        session_id, runtime, model = self._ended
        head = update["head"] if "head" in update else state.head
        session = AgentSession(
            session_id=session_id,
            runtime=runtime,
            model=model,
            node=node,
            round=_round(node, state),
            head=head,
        )
        kept: Update = {"sessions": {**state.sessions, role: session}}
        if role is SessionRole.BUILD and not state.build_model:
            kept["build_model"] = model
        return kept

    async def gate(self, node: Node, state: UnitRun) -> None:
        """Interrupt before an agent step the usage guard refuses.

        At the node's boundary and never inside it: a step that is running is
        let finish. The resume asks the guard again, so the interrupt carries
        only what a person reading the thread needs.
        """
        allowed, why = await asyncio.to_thread(self.runner.may_start)
        if allowed:
            if self.paused_since is not None:
                self._node = node.value
                spans.record_span(
                    self.paused_since,
                    self.say,
                    unit=self.unit.id,
                    change=self.unit.change,
                    node=node.value,
                    round_number=_round(node, state),
                    waited=spans.USAGE_PAUSE,
                )
                self.paused_since = None
            return
        until = await asyncio.to_thread(self.runner.resume_at)
        self._node = node.value
        self.say(f"paused before the agent step: {why}")
        # Carried in the interrupt, which outlives the process: the run that
        # resumes the thread is a later one, and measures the pause from it.
        began = self.paused_since.at if self.paused_since else spans.clock.now()
        interrupt(
            {"reason": why, "until": until.isoformat() if until else None, "at": began.isoformat()}
        )

    def _step(self, node: Node, body: Callable[[UnitRun], Update], state: UnitRun) -> Update:
        # Between steps, never inside one: a held unit has finished the step it was in.
        gated = (
            node in GATED
            or (node is Node.TIER1 and state.produced_nothing and not state.moved)
            or (node is Node.PUSH and state.spent)
            or (node is Node.TIER2 and not state.moved)
        )
        if gated and (found := self.upstream_changed(state)):
            cause, why = found
            return self.hold(
                PLANNED,
                f"held before {node.value}: {why}",
                f"held before {node.value} — {why}",
                cause=cause,
            )
        return body(state)

    def upstream_changed(self, state: UnitRun) -> tuple[Cause, str] | None:
        """Why the unit should not go on yet, with the cause: something upstream
        went back for rework, or the base it was built on moved or was rewritten."""
        unit, r = self.unit, self.runner
        base = state.base or self.base
        return r.upstream_incomplete(unit) or r.base_moved(
            unit, base, tree=self.tree(), start=state.start
        )

    def hold(
        self,
        state: UnitState,
        note: str,
        detail: str,
        *,
        cause: Cause,
        pr: int | None = None,
        held_by: HeldBy = HeldBy.NONE,
    ) -> Update:
        """Stop the run in `held`, with the store left in `state`.

        Recorded here and not by the `held` node, which waits: a node that waits
        runs again from its start when its interrupt is resumed, and would write
        over whatever the event that resumed it had recorded.
        """
        self.say(f"held: {note}")
        opened: dict[str, Any] = {"pr": pr} if pr else {}
        self.runner.store.set_state(
            self.unit.id, state, note=note, held_by=held_by, cause=cause, **opened
        )
        update: Update = {
            "held": detail,
            "hold_state": state,
            "hold_note": note,
            "status": RunStatus.HELD,
            "detail": detail,
        }
        return {**update, "pr": pr} if pr else update

    def _chat_changes(self) -> bool:
        """Whether a chat left uncommitted changes under a lease whose server has gone: they
        are the person's to commit or discard, never a killed run's leftovers."""
        leases = self.runner.leases
        held = leases.attachment(self.unit.id) if leases is not None else None
        return held is not None and held.stale and held.changed > 0

    def park(self, error: DirtyWorktree) -> Update:
        """Hold the unit for a tree that is not the running node's own, touching nothing in it."""
        if self._chat_changes():
            why = (
                f"uncommitted changes from a chat in the worktree: {_listed(error.paths)} "
                "— start the server, or run `abk attach release` to commit or discard them"
            )
            return self.hold(HELD, why, why, cause=Cause.ATTACHED)
        why = (
            f"uncommitted changes in the worktree: {_listed(error.paths)} "
            "— commit or remove them by hand"
        )
        return self.hold(HELD, why, why, cause=Cause.DIRTY_WORKTREE)

    def rebase(
        self, state: UnitRun, why: str, *, base: str, lead: str = "base moved before its push"
    ) -> Update:
        """Go back to the restack now, once, rather than queue; a second time holds,
        so a base that keeps moving cannot loop."""
        note = f"{lead}: {why}"
        if state.rebased:
            return self.hold(PLANNED, note, note, cause=Cause.BASE_CHANGED)
        self.say(f"held: {note}; resuming at its restack on {base}")
        return {"restack": True, "rebased": True, "base": base}

    def agent(
        self,
        run: Callable[..., str],
        *args: str,
        cwd: Path,
        state: UnitRun,
        model: str = "",
        follow_up: str = "",
        session: AgentSession | None = None,
        **inputs: Any,
    ) -> str:
        """One agent run, continuing the session a killed run of this node left, or the
        role's latest session (or the `session` given) when the node has a `follow_up` to say to it.

        `args` and `inputs` are what `run` is called with besides the worktree,
        the model and the session; `args[0]` is the full prompt. A session the
        runtime cannot continue is not an error: the node runs from its start in
        a new session on `model`, as it would have without a recorded id.
        """
        place = f"{self.unit.id}:{self._node}:{_round(Node(self._node), state)}"
        token = attribution.set(place)
        try:
            return self._run_agent(
                run,
                args,
                cwd=cwd,
                state=state,
                model=model,
                follow_up=follow_up,
                session=session,
                inputs=inputs,
            )
        finally:
            attribution.reset(token)

    def _run_agent(
        self,
        run: Callable[..., str],
        args: tuple[str, ...],
        *,
        cwd: Path,
        state: UnitRun,
        model: str,
        follow_up: str,
        session: AgentSession | None,
        inputs: dict[str, Any],
    ) -> str:
        if state.session_id:
            self.say(f"continuing agent session {state.session_id}")
            # A session this node's role recorded keeps the model and runtime it began on.
            role = SESSION_ROLES.get(Node(self._node))
            held = state.sessions.get(role) if role else None
            if held is not None and held.session_id == state.session_id:
                model, resume_runtime = held.model or model, held.runtime
            else:
                resume_runtime = ""
            # Before the run, so a run killed again still leaves the trace; a session that
            # cannot be continued is counted again as a new one below.
            self._resuming_over_leftovers("resumed")
            try:
                return run(
                    *args,
                    cwd=cwd,
                    **_model(model),
                    resume_session=state.session_id,
                    **({"resume_runtime": resume_runtime} if resume_runtime else {}),
                    on_session=self.on_session,
                    on_result=self._recorder(state, resumed=True),
                    **inputs,
                )
            except SessionUnavailable as error:
                self.say(
                    f"session {state.session_id} cannot be continued ({error}); "
                    "running the node from its start in a new session"
                )
        elif follow_up:
            found, why = self._continuable(state, cwd, session)
            if found is not None:
                try:
                    return self._continue(
                        run,
                        args,
                        found,
                        cwd=cwd,
                        state=state,
                        model=model,
                        follow_up=follow_up,
                        inputs=inputs,
                    )
                except SessionUnavailable as error:
                    why = str(error)
            if why:
                self.say(
                    f"the {SESSION_ROLES[Node(self._node)]} session cannot be continued ({why}); "
                    "running the node from its start in a new session"
                )
        if self._leftovers:
            self._resuming_over_leftovers("new")
            note = LEFTOVERS_NOTE.format(paths=_listed(self._leftovers))
            args = (f"{args[0]}\n\n{note}", *args[1:])
        return run(
            *args,
            cwd=cwd,
            **_model(model),
            on_session=self.on_session,
            on_result=self._recorder(state, resumed=False),
            **inputs,
        )

    def _continuable(
        self, state: UnitRun, cwd: Path, given: AgentSession | None = None
    ) -> tuple[AgentSession | None, str]:
        """The session this node may continue (the `given` one, else the role's recorded one),
        or why it may not: nothing when reuse is off or there is none yet, which is not a
        reason to say."""
        role = SESSION_ROLES.get(Node(self._node))
        if role is None or not active().reuses_session(role.value):
            return None, ""
        if (session := given or state.sessions.get(role)) is None:
            return None, ""
        if session.head and not self.runner.head_reachable(cwd, session.head):
            return None, f"the commit {session.head} it last saw is gone from the worktree"
        return session, ""

    def _continue(
        self,
        run: Callable[..., str],
        args: tuple[str, ...],
        session: AgentSession,
        *,
        cwd: Path,
        state: UnitRun,
        model: str,
        follow_up: str,
        inputs: dict[str, str],
    ) -> str:
        """The node's `follow_up` said to `session`, which says first what moved on the branch
        since it last spoke."""
        if self._leftovers:
            follow_up = f"{LEFTOVERS_NOTE.format(paths=_listed(self._leftovers))}\n\n{follow_up}"
        head = self.runner.head(cwd)
        if session.head and head != session.head:
            follow_up = f"{MOVED_NOTE.format(old=session.head, new=head)}\n\n{follow_up}"
        self.say(
            f"continuing the {SESSION_ROLES[Node(self._node)]} session {session.session_id}"
            f" on {session.model or model}"
        )
        result = run(
            *args,
            cwd=cwd,
            **_model(session.model or model),
            resume_session=session.session_id,
            follow_up=follow_up,
            resume_runtime=session.runtime,
            on_session=self.on_session,
            on_result=self._recorder(state, resumed=True),
            **inputs,
        )
        # Counted once the call has gone through, so a continuation that falls back to a new
        # session is counted only as that.
        self._resuming_over_leftovers("resumed")
        return result

    def _resuming_over_leftovers(self, session: str) -> None:
        if not self._leftovers:
            return
        self.say(
            f"resuming over uncommitted work in {len(self._leftovers)} file(s), session {session}"
        )
        telemetry.count("abk.leftovers.resumed", node=self._node, session=session)

    def _recorder(self, state: UnitRun, *, resumed: bool) -> Callable[..., None]:
        """What an agent call tells when it finishes: one line for the usage ledger."""
        unit, node = self.unit, self._node
        round_number = _round(Node(node), state)

        def record(
            result: AgentResult,
            *,
            role: str,
            model: str | None,
            runtime: str,
            gateway: Callable[[], Spend] | None = None,
        ) -> None:
            # What the gateway logged for the call's own key is exact; what the
            # agent said is kept beside it, for the report to compare.
            if result.session_id:
                self._ended = (result.session_id, runtime, model or "")
            spent = gateway() if gateway else Spend()
            exact = spent.usage is not None
            usage = (spent.usage if exact else result.usage) or Usage()
            line = UsageRecord(
                at=datetime.now(UTC).isoformat(),
                unit=unit.id,
                node=node,
                round=round_number,
                change=unit.change,
                repo=unit.repo,
                tier=unit.tier,
                role=role,
                model=model,
                runtime=runtime,
                session_id=result.session_id,
                resumed=resumed,
                **usage.model_dump(),
                cost_usd=spent.cost_usd if exact else result.cost_usd,
                turns=result.turns,
                duration_ms=result.duration_ms,
                usage_source="gateway" if exact else result.usage_source,
                reported=result.usage if exact else None,
                reported_cost_usd=result.cost_usd if exact else None,
                outcome="ok" if result.succeeded else "failed",
            )
            record_call(line, self.say)

        return record

    def record_check_failure(self, output: str, round: int) -> None:
        """Keep a failed tier 1 run of this unit as a local metric record."""
        try:
            check = failed_check(output, self.unit.repo)
        except Exception:  # noqa: BLE001 — a record is never a run's to lose
            check = "unknown"
        record_metric(
            "abk.checks.failures",
            1,
            self.runner.log,
            unit=self.unit.id,
            change=self.unit.change,
            check=check,
            round=round,
        )

    def say(self, message: str) -> None:
        """A progress line, for the tick log and the unit's run log."""
        line = f"{self._node}: {message}"
        self.runner.log(line)
        # The tick's logger already copies the line, stamped, into its run log.
        if self.run_log and not self.runner.log_reaches_run_log:
            self.run_log.emit(line)

    def stop(self, reason: str) -> Update:
        self.say(f"stopping: {reason}")
        return {"stopped": reason}

    def tree(self) -> Path:
        if self._tree is None:
            base = local_ref(self.base, repo=self.unit.repo)
            try:
                self._tree = self.runner.worktree(self.unit, base)
            except DirtyWorktree as dirty:
                if not self._own or self._chat_changes():
                    raise
                self._tree = self.runner.worktree(self.unit, base, allow_dirty=True)
                self._leftovers = dirty.paths
        return self._tree

    def ref(self, state: UnitRun) -> str:
        return local_ref(state.base or self.base, repo=self.unit.repo)

    def outside_note(self, state: UnitRun, tree: Path) -> str:
        """The prompt part listing commits made to the branch outside the build session."""
        held = state.sessions.get(SessionRole.BUILD)
        repo = self.runner.repo_config
        profile = profiles.get(repo.profile if repo else "python-uv")
        return outside_commits_note(
            tree,
            self.ref(state),
            held.session_id if held else "",
            is_test=profile.is_test_path,
        )

    @staticmethod
    def told(text: str, note: str) -> str:
        return f"{text}\n\n{note}" if note else text

    def prepare(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        branch = branch_name(unit)
        base = state.base or self.base
        feedback = r.store.get(unit.id).feedback
        r.store.set_state(unit.id, UnitState.RUNNING, branch=branch)
        # Made again: a trip back here may be onto a different base.
        self._tree = None
        tree, ref = self.tree(), self.ref(state)
        # Taken before the restack and any adapt, so a base rewritten during
        # them is caught too: a parent restacked meanwhile keeps its name.
        start = r.base_tip(tree, ref)
        existing = r.branch_commits(tree, ref)
        self.say(
            f"on {base}, {existing} commit(s) on the branch"
            + (", with feedback to address" if feedback else "")
        )
        if existing:
            # Before reviewing or pushing: a base force-pushed underneath the
            # branch would have the work judged against commits it does not have.
            r.fetch_quietly(unit)
            try:
                restacked = r.restack_onto(tree=tree, branch=branch, base=ref, unit=unit)
            except (AgentRateLimited, AgentInterrupted):
                raise
            except Exception as error:  # noqa: BLE001
                why = f"restack onto {base} conflicted: {error}"
                stored = r.store.get(unit.id)
                r.store.set_feedback(
                    unit.id,
                    f"{stored.feedback}\n\n{why}".strip(),
                    from_person=stored.feedback_from_person,
                    source=stored.feedback_source,
                )
                return {**FRESH, **self.stop(why)}
            if restacked is not None:
                if restacked.conflict:
                    return {**FRESH, "start": start, "head": r.head(tree), "conflict": restacked}
                if restacked.resolved:
                    files = ", ".join(restacked.resolved)
                    self.say(f"restacked onto {base}, resolving {files}")
                    r.store.set_predecessor_note(
                        unit.id,
                        PREDECESSOR_NOTE.format(
                            onto_unit=restacked.onto_unit,
                            how=f"moving onto it needed conflict resolution in {files}",
                            decisions="",
                        ),
                    )
                else:
                    self.say(f"restacked onto {base} cleanly")
                existing = r.branch_commits(tree, ref)
        return {
            **FRESH,
            **self.standing(existing, feedback),
            "start": start,
            "tier2": unit.tier == "tier2",
        }

    def standing(self, existing: int, feedback: str) -> Update:
        """What the branch holds, which is what the path from here is chosen on."""
        r, unit = self.runner, self.unit
        head = r.head(self.tree())
        stored = r.store.get(unit.id)
        return {
            "pushed_head": bool(existing) and head == stored.approved == stored.pushed,
            "opened": stored.pr is not None,
            "base_commits": existing,
            "had_feedback": bool(feedback),
            "head": head,
            "head_approved": bool(existing) and head == r.store.get(unit.id).approved,
        }

    def adapt(self, state: UnitRun) -> Update:
        """Port the unit onto a predecessor it could not be replayed onto.

        The branch is reset to the new base, the old work kept under a ref, and
        the rework model ports it, deciding for each previous test the port did
        not carry over unchanged whether it still belongs. Those decisions are
        checked here, then handed to the reviewer, who judges them.
        """
        r, unit = self.runner, self.unit
        restacked = state.conflict
        assert restacked is not None
        tree, ref = self.tree(), self.ref(state)
        change_dir, groups = r.scope(unit)
        self.say(
            f"adapt onto {restacked.onto_unit}, the restack could not be merged ({models().rework})"
        )
        keep = f"refs/spec-driven/pre-adapt/{unit.id}"
        if r.head(tree) == state.head:
            r.reset_to(tree, ref, keep)
        # Otherwise a killed run already reset the branch: resetting again would
        # overwrite `keep` with the half-ported tree and lose the old work.
        answer = self.agent(
            r.run,
            ADAPT_PROMPT.format(
                change_dir=change_dir,
                groups=groups,
                onto_unit=restacked.onto_unit,
                onto_intent=restacked.onto_intent,
                conflict=restacked.conflict[:2000],
                old_ref=keep,
                old_base=restacked.old_base,
                tests="\n".join(f"- `{name}`" for name in restacked.old_tests),
            ),
            cwd=tree,
            state=state,
            model=models().rework,
            follow_up=ADAPT_CONTINUATION.format(
                onto_unit=restacked.onto_unit,
                onto_intent=restacked.onto_intent,
                conflict=restacked.conflict[:2000],
                old_ref=keep,
                old_base=restacked.old_base,
                tests="\n".join(f"- `{name}`" for name in restacked.old_tests),
            ),
        )
        r.commit(f"adapt: {unit.title} onto {restacked.onto_unit}", cwd=tree)
        # The session that did the port: the follow-up rounds continue it, and it is the one
        # recorded for the role whatever they do.
        ported = self._ended
        # Only now does the tree hold what the agent carried over.
        present = r.tests_in(tree)
        changed = r.tests_changed(tree, keep)
        required = tests_needing_decision(restacked.old_tests, present, changed)
        decisions = parse_test_decisions(answer)
        problems = check_test_decisions(required, decisions, present, changed)
        # Put back to the agent, bounded: the code already landed with the commit above.
        for _ in range(active().limits.max_adapt_rounds - 1):
            if not problems:
                break
            listed = "\n".join(f"- {p}" for p in problems)
            answer = self.agent(
                r.run,
                ADAPT_FOLLOWUP_PROMPT.format(problems=listed),
                cwd=tree,
                state=state,
                model=models().rework,
                follow_up=ADAPT_FOLLOWUP_PROMPT.format(problems=listed),
                session=self.ported_session(ported, state, r.head(tree)),
            )
            # Merged over the first answer's: an agent that answers only for the
            # tests just named must not lose the decisions it already gave.
            by_name = {d.name: d for d in decisions}
            by_name.update({d.name: d for d in parse_test_decisions(answer)})
            decisions = list(by_name.values())
            problems = check_test_decisions(required, decisions, present, changed)
        # A follow-up that could not continue the port's session opened one that has seen
        # only the accounting; the port's is the one to keep.
        self._ended = ported
        if problems:
            why = "the adapt step did not account for its tests: " + "; ".join(problems)
            outstanding = [n for n in required if any(f"`{n}`" in p for p in problems)]
            if outstanding:
                why += "\n\noutstanding: " + ", ".join(f"`{n}`" for n in outstanding)
            stored = r.store.get(unit.id)
            r.store.set_feedback(
                unit.id,
                f"{stored.feedback}\n\n{why}".strip(),
                from_person=stored.feedback_from_person,
                source=stored.feedback_source,
            )
            return self.stop(why)
        r.store.set_predecessor_note(unit.id, self.port_note(restacked, required, decisions))
        counts = {k: sum(d.decision == k for d in decisions) for k in ("keep", "adapt", "retire")}
        self.say(
            f"adapted: {counts['keep']} kept, {counts['adapt']} adapted, {counts['retire']} retired"
        )
        feedback = r.store.get(unit.id).feedback
        return {"conflict": None, **self.standing(r.branch_commits(tree, ref), feedback)}

    def ported_session(
        self, ended: tuple[str, str, str] | None, state: UnitRun, head: str
    ) -> AgentSession | None:
        """The session the port ran in, as the adapt follow-up rounds continue it."""
        if ended is None:
            return None
        session_id, runtime, model = ended
        return AgentSession(
            session_id=session_id,
            runtime=runtime,
            model=model,
            node=Node.ADAPT,
            round=_round(Node.ADAPT, state),
            head=head,
        )

    @staticmethod
    def port_note(restacked: Restacked, required: Any, decisions: Any) -> str:
        rendered = "".join(
            f"\n- `{d.name}`: {d.decision}" + (f" — {d.reason}" if d.reason else "")
            for d in decisions
        )
        auto_kept = [name for name in restacked.old_tests if name not in required]
        kept_note = (
            "\n\nCarried over unchanged, so counted as kept without being asked about: "
            + ", ".join(f"`{name}`" for name in auto_kept)
            if auto_kept
            else ""
        )
        return PREDECESSOR_NOTE.format(
            onto_unit=restacked.onto_unit,
            how="replaying this unit onto it conflicted, so its work was ported onto the "
            "new version by hand",
            decisions=(
                f"The port decided, for its previous tests:{rendered}{kept_note}\n\nJudge "
                "each decision, retirements especially. "
            )
            if decisions or auto_kept
            else "",
        )

    def tests(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        if r.head(tree) != state.head:
            self.say("the tests commit is already on the branch")
        else:
            change_dir, groups = r.scope(unit)
            build_boundary, _ = r.boundary_notes(unit, self.graph)
            self.say(f"write the tests ({models().implement})")
            prompt = TESTS_PROMPT.format(
                groups=groups,
                change_dir=change_dir,
                boundary=build_boundary,
                changelog=changelog_note(tree, r.repo_config),
            )
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            self.agent(r.run, prompt, cwd=tree, state=state, model=models().implement)
            r.commit(f"test: {unit.title}", cwd=tree)
        return {"head": r.head(tree)}

    def implement(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, ref = self.tree(), self.ref(state)
        if r.head(tree) != state.head:
            self.say("the implementation commit is already on the branch")
        else:
            change_dir, groups = r.scope(unit)
            build_boundary, _ = r.boundary_notes(unit, self.graph)
            self.say(f"implement ({models().implement})")
            prompt = IMPLEMENTATION_PROMPT.format(
                groups=groups,
                change_dir=change_dir,
                boundary=build_boundary,
                changelog=changelog_note(tree, r.repo_config),
            )
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            self.agent(
                r.run,
                prompt,
                cwd=tree,
                state=state,
                model=models().implement,
                follow_up=IMPLEMENTATION_CONTINUATION.format(
                    changelog=changelog_note(tree, r.repo_config)
                ),
            )
            r.commit(f"feat: {unit.title}", cwd=tree)
        # Counted on the branch, not taken from the commit step: an agent that
        # commits its own work leaves the pipeline nothing to commit.
        return {"head": r.head(tree), "produced_nothing": r.branch_commits(tree, ref) == 0}

    def checks(self, state: UnitRun) -> Update:
        """Tier 1 on the committed branch, before a reviewer is asked."""
        r, unit = self.runner, self.unit
        tree = self.tree()
        self.say("checks before review")
        ok, output = r.run_tier1(cwd=tree, base=self.ref(state), whole_repo=False)
        self.say(f"checks {'passed' if ok else 'failed'}")
        head = r.head(tree)
        if ok:
            if r.store.get(unit.id).feedback_source is FeedbackSource.TIER1:
                # Fixed: left saved, a resume would redo a fix already on the branch.
                r.store.set_feedback(unit.id, "")
            return {"checks_ok": True, "head": head}
        self.say(output)
        telemetry.count(
            "abk.checks.failures",
            check=lambda: failed_check(output, unit.repo),
            round=state.fix_rounds + 1,
        )
        self.record_check_failure(output, state.fix_rounds + 1)
        # Kept before anything can stop the run, so a retry addresses this output.
        r.store.set_feedback(
            unit.id, f"{TIER1_FAILED}\n{output}".strip(), source=FeedbackSource.TIER1
        )
        budget = active().limits.max_check_rounds
        if budget is not None and state.fix_rounds >= budget:
            return {
                **self.stop(f"checks still failing after {budget} fix round(s), before review"),
                "checks_ok": False,
                "head": head,
            }
        return {"checks_ok": False, "head": head}

    def fix_checks(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        change_dir, groups = r.scope(unit)
        build_boundary, _ = r.boundary_notes(unit, self.graph)
        attempt = state.fix_rounds + 1
        if r.head(tree) == state.head:
            # The model that wrote the code fixes it, whatever the configuration says now.
            model = state.build_model or models().implement
            feedback = r.store.get(unit.id).feedback
            self.say(f"fix the failing checks ({model}), round {attempt}")
            outside = self.outside_note(state, tree)
            self.agent(
                r.run,
                self.told(
                    CHECKS_PROMPT.format(
                        change_dir=change_dir,
                        groups=groups,
                        feedback=feedback,
                        boundary=build_boundary,
                    ),
                    outside,
                ),
                cwd=tree,
                state=state,
                model=model,
                follow_up=self.told(CHECKS_CONTINUATION.format(feedback=feedback), outside),
            )
            r.commit(f"fix: {unit.title} (checks, round {attempt})", cwd=tree)
            if r.head(tree) == state.head:
                return self.stop(
                    f"checks failing and fix round {attempt} changed nothing, before review"
                )
        else:
            self.say(f"fix round {attempt} is already on the branch")
        return {"fix_rounds": attempt, "head": r.head(tree)}

    def review(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        _, review_boundary = r.boundary_notes(unit, self.graph)
        total = active().limits.max_review_rounds
        round_number = state.review_round
        zero = state.adopted  # a chat's commit: reviewed, but no place in the round limit
        reworking = zero or state.had_feedback or bool(r.store.get(unit.id).predecessor_note)
        first = round_number == 0 and not reworking
        # A fresh build starts a fresh loop; a reworking one carries the rounds it had.
        rounds = () if first else state.review_rounds
        judged = r.head(tree)
        model = models().review if first else models().rework_review
        self.say(
            f"review of a chat's commit ({model})"
            if zero
            else f"review round {round_number + 1} ({model})"
        )
        context: dict[str, Any] = r.review_notes(
            unit,
            round_number=round_number,
            total=total,
            round_zero=zero,
            review_boundary=review_boundary,
            rounds=rounds,
            person_comments=state.person_comments,
            pending_replies=state.pending_replies,
        )
        if outside := self.outside_note(state, tree):
            context = {**context, "context": self.told(context.get("context", ""), outside).strip()}
        raw = self.agent(
            r.run_review if first else r.run_rework_review, cwd=tree, state=state, **context
        )
        weighed = r.weigh_review(unit, raw, judged=judged, rounds=rounds)
        update: Update = {
            "review_round": round_number if zero else round_number + 1,
            "adopted": False,
            "head": judged,
            "review_rounds": weighed.rounds,
            # Kept past the push, which clears the rounds: the review tab shows it.
            "last_findings": weighed.findings,
        }
        if weighed.approved:
            return {
                **update,
                "verdict": Verdict.APPROVED,
                "deferred": weighed.deferred,
                "fix_rounds": 0,
            }
        verdict = weighed.verdict
        if verdict.needs_human:
            # What is left is something the builder's environment refuses: asking
            # again spends rounds on a change it can never make.
            why = weighed.why
            r.store.set_feedback(unit.id, why)
            return {
                **update,
                **self.hold(
                    HELD,
                    f"needs a human: {why[:300]}",
                    f"needs a human: {why[:200]}",
                    cause=Cause.NEEDS_HUMAN,
                    held_by=HeldBy.REVIEW,
                ),
            }
        if escalates(verdict, weighed.earlier_rounds):
            # Another instance of a kind that cannot be enumerated, or a point
            # raised again after the builder declined it: a person's call.
            parts = [weighed.why]
            if verdict.escalate is Escalation.DISAGREEMENT:
                parts.append(str(weighed.earlier_rounds[-1].get("response", "")).strip())
            parts.append(verdict.reasoning)
            r.store.set_feedback(unit.id, "\n\n".join(p for p in parts if p).strip())
            label = (
                "an open-ended class"
                if verdict.escalate is Escalation.CLASS
                else "a repeated disagreement"
            )
            escalated = (
                Cause.REVIEW_ESCALATED_CLASS
                if verdict.escalate is Escalation.CLASS
                else Cause.REVIEW_ESCALATED_DISAGREEMENT
            )
            reasoning = " ".join(verdict.reasoning.split())[:280]
            return {
                **update,
                **self.hold(
                    HELD,
                    f"escalated — {label} ({verdict.escalate}): {reasoning}",
                    f"escalated ({verdict.escalate}): {reasoning[:200]}",
                    cause=escalated,
                    held_by=HeldBy.REVIEW,
                ),
            }
        # Kept as feedback, so the rework addresses what this round asked for, or
        # a person who inherits the branch reads what is outstanding.
        r.store.set_feedback(unit.id, weighed.why)
        if zero:
            # Counted rounds start at one with the rework this asks for.
            return {**update, "verdict": Verdict.CHANGES, "fix_rounds": 0, "review_round": 1}
        if round_number >= total - 1:
            # The last round's review is the verdict: a rework after it would never be reviewed.
            return {**update, "spent": True}
        return {**update, "verdict": Verdict.CHANGES, "fix_rounds": 0}

    def rework(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, ref = self.tree(), self.ref(state)
        change_dir, groups = r.scope(unit)
        build_boundary, _ = r.boundary_notes(unit, self.graph)
        stored = r.store.get(unit.id)
        feedback = stored.feedback
        failed_check = stored.feedback_source in (FeedbackSource.TIER1, FeedbackSource.TIER2)
        in_loop = state.verdict is Verdict.CHANGES
        kept: Update = {}
        outside = self.outside_note(state, tree)
        # An empty head is a rework just delivered by an event: no node has recorded the
        # branch's tip, so nothing is known to be done. `new_comments` records the tip,
        # which is the worktree's HEAD,
        # so its rework runs and a resume after the agent's commit sees a different head.
        if state.head and r.head(tree) != state.head:
            self.say("the rework commit is already on the branch")
        elif in_loop:
            self.say(f"address review round {state.review_round} ({models().rework})")
            response = self.agent(
                r.run,
                self.told(
                    REVIEW_FEEDBACK_PROMPT.format(
                        change_dir=change_dir,
                        groups=groups,
                        feedback=feedback,
                        boundary=build_boundary,
                        changelog=changelog_note(tree, r.repo_config),
                    ),
                    outside,
                ),
                cwd=tree,
                state=state,
                model=models().rework,
                follow_up=self.told(
                    REVIEW_FEEDBACK_CONTINUATION.format(
                        feedback=feedback, changelog=changelog_note(tree, r.repo_config)
                    ),
                    outside,
                ),
            )
            kept["review_rounds"] = with_response(state.review_rounds, response)
            r.commit(f"fix: {unit.title} (review round {state.review_round})", cwd=tree)
        else:
            # One run on the review model, not the tests-then-implementation
            # pair: both are already on the branch.
            self.say(f"rework from feedback ({models().rework})")
            if stored.pr and not failed_check and state.seen_comments is None:
                # A requeued rework, which no event delivered: its feedback was fixed at the
                # requeue, so these ids are only marked seen. None is known to have reached the
                # agent, and the poller reports again any it was not given.
                kept["seen_comments"] = self.covered(stored.pr)
            answer = self.agent(
                r.run,
                self.told(
                    CHECKS_PROMPT.format(
                        groups=groups,
                        change_dir=change_dir,
                        feedback=feedback,
                        boundary=build_boundary,
                    )
                    if failed_check
                    else REWORK_PROMPT.format(
                        groups=groups,
                        change_dir=change_dir,
                        feedback=feedback,
                        pr=stored.pr or "(not yet opened)",
                        boundary=build_boundary,
                        changelog=changelog_note(tree, r.repo_config),
                    ),
                    outside,
                ),
                cwd=tree,
                state=state,
                model=models().rework,
                follow_up=self.told(
                    CHECKS_CONTINUATION.format(feedback=feedback)
                    if failed_check
                    else REWORK_CONTINUATION.format(
                        feedback=feedback,
                        pr=stored.pr or "(not yet opened)",
                        changelog=changelog_note(tree, r.repo_config),
                    ),
                    outside,
                ),
            )
            r.commit(f"fix: {unit.title}", cwd=tree)
            if answer and stored.pr and not failed_check:
                # Only an existing pull request has a reviewer waiting in its threads.
                kept["pending_replies"] = (*state.pending_replies, answer)
                if stored.feedback_from_person:
                    kept["person_comments"] = f"{state.person_comments}\n\n{feedback}".strip()
        return {
            **kept,
            "comments_pending": False,
            "verdict": None,
            "fix_rounds": 0,
            "head": r.head(tree),
            "produced_nothing": r.branch_commits(tree, ref) == 0,
        }

    def covered(self, pr: int) -> tuple[str, ...] | None:
        """Every comment id on the pull request now, or None when the host could not say."""
        try:
            return tuple(
                c.id for c in self.runner.fetch_comments(self.unit.repo, pr, branch_name(self.unit))
            )
        except Exception as error:  # noqa: BLE001
            self.say(f"could not read the comments on #{pr}: {error}")
            return None

    def new_comments(self, state: UnitRun) -> Update:
        """Before the push, comments the rework was not given go back to it."""
        r, unit = self.runner, self.unit
        pr = r.store.get(unit.id).pr
        # No `seen_comments` means no rework of a unit with a pull request is under way (or
        # the delivery could not read the host, and nothing was recorded as given).
        if not pr or state.seen_comments is None:
            return {}
        try:
            now = r.fetch_comments(unit.repo, pr, branch_name(unit))
        except Exception as error:  # noqa: BLE001
            # The work is done and reviewed: a host that did not answer does not hold it back.
            self.say(f"could not read the comments on #{pr} again, pushing: {error}")
            return {}
        new = [c for c in now if c.id not in state.seen_comments and not c.own]
        words = "\n".join(c.words for c in new if c.words)
        seen = (*state.seen_comments, *(c.id for c in new))
        if not words:
            return {"seen_comments": seen}
        # Given with this pass, so the poller does not report them again after the push.
        # When a pass carries words, every id it took in is given, including GitHub's body-less
        # review for an inline comment; a pass with no words gives nothing and leaves those ids
        # to the poller.
        given = (*state.given_comments, *(c.id for c in new))
        self.say(f"{len(new)} new comment(s) on #{pr}: back to rework")
        r.store.set_feedback(unit.id, words, from_person=True, source=FeedbackSource.REVIEW)
        return {
            "seen_comments": seen,
            "given_comments": given,
            "comments_pending": True,
            "verdict": None,
            "review_round": 0,
            "fix_rounds": 0,
            "head": r.head(self.tree()),
        }

    def tier1(self, state: UnitRun) -> Update:
        """For a unit that produced nothing, and for a branch moved cleanly onto a new base."""
        r, unit = self.runner, self.unit
        base = state.base or self.base
        self.say("tier 1")
        ok, output = r.run_tier1(
            cwd=self.tree(), base=self.ref(state), whole_repo=state.produced_nothing
        )
        self.say(f"tier 1 {'passed' if ok else 'failed'}")
        if not ok:
            self.say(output)
            telemetry.count(
                "abk.checks.failures", check=lambda: failed_check(output, unit.repo), round=0
            )
            self.record_check_failure(output, 0)
            r.store.set_feedback(
                unit.id, f"{TIER1_FAILED}\n{output}".strip(), source=FeedbackSource.TIER1
            )
            if state.moved:
                return self.rebase(state, f"tier 1 failed on {base}", base=base)
            return self.stop("tier 1 failed")
        if (
            state.moved
            and not state.produced_nothing
            and r.head(self.tree()) != r.store.get(unit.id).approved
        ):
            # Moved cleanly, but not as the same change: review has not read this commit.
            return self.rebase(
                state,
                f"moving onto {base} changed what review approved, so it is read again",
                base=base,
            )
        return {}

    def tier2(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        base = state.base or self.base
        self.say("tier 2 again on the moved commit" if state.moved else "tier 2")
        ok, snapshot = r.run_tier2(cwd=self.tree())
        self.say(f"tier 2 {'passed' if ok else 'failed'}")
        if ok:
            return {"snapshot": snapshot}
        # The tail goes to the run log too: the run log is where a failed run is read.
        for line in [line for line in snapshot.splitlines() if line.strip()][-TIER2_LOG_TAIL:]:
            self.say(line)
        # Kept, as tier 1's is: a failure that leaves no trace has to be reproduced by hand.
        if state.moved:
            r.store.set_feedback(
                unit.id, f"tier 2 failed:\n{snapshot}".strip(), source=FeedbackSource.TIER2
            )
            return self.rebase(state, f"tier 2 failed on {base}", base=base)
        stored = r.store.get(unit.id)
        # Words a person left stay theirs: tier 2's output is added to them, not
        # the other way round.
        review = stored.feedback_source is FeedbackSource.REVIEW
        r.store.set_feedback(
            unit.id,
            f"{stored.feedback}\n\ntier 2 failed:\n{snapshot}".strip(),
            from_person=stored.feedback_from_person,
            source=FeedbackSource.REVIEW if review else FeedbackSource.TIER2,
        )
        return self.stop("tier 2 failed")

    def satisfied(self, state: UnitRun) -> Update:
        """Nothing of this unit's own on the branch, and what is at the tip passes:
        the work its groups called for arrived another way. Judged on the branch
        and the checks, never on a step's report of itself."""
        r, unit = self.runner, self.unit
        self.say("nothing to add and tier 1 passes — satisfied")
        r.store.set_state(unit.id, SATISFIED, note="already implemented; tier 1 passed")
        # A satisfied unit is done: nothing here should look like a build in progress.
        if r.store.get(unit.id).predecessor_note:
            r.store.set_predecessor_note(unit.id, "")
        # The review feedback and its replies belong to a build this unit is no longer doing.
        if r.store.get(unit.id).feedback:
            r.store.set_feedback(unit.id, "")
        stored = r.store.get(unit.id)
        # First: a dependent left on this unit's branch would be pointing at a
        # closed pull request. One that cannot be moved is logged, not raised,
        # and recorded on the unit, or it looks like a clean release.
        note = "; ".join(["already implemented; tier 1 passed", *r.release_dependents(stored)])
        if note != stored.note:
            r.store.set_state(unit.id, SATISFIED, note=note)
        if stored.pr:
            # Posting and closing are one call, so the reason is never missing before the close.
            reason = satisfied_reason(stored, graph=self.graph or [stored])
            try:
                r.close_pr(unit, stored.pr, reason)
            except Exception as error:  # noqa: BLE001
                # Kept, so a later pass repeats the pair until the pull request is closed.
                r.store.set_close_pending(unit.id, ClosePending(pr=stored.pr, reason=reason))
                # The unit stays satisfied, but the failure is recorded on the unit
                # itself, or it looks like one whose close worked.
                self.say(f"{unit.id}: pull request #{stored.pr} not closed — {error}")
                r.store.set_state(
                    unit.id, SATISFIED, note=f"{note}; PR #{stored.pr} not closed — {error}"
                )
        r.mark_tasks(unit, done=True)
        return {
            "status": RunStatus.SATISFIED,
            "detail": "already implemented; tier 1 passed",
            "review_rounds": (),
            "pending_replies": (),
            "person_comments": "",
            "seen_comments": None,
            "given_comments": (),
        }

    def verify_base(self, state: UnitRun) -> Update:
        """The base as it is now, before anything is pushed against it."""
        r, unit = self.runner, self.unit
        base = state.base or self.base
        r.fetch_quietly(unit)
        try:
            fresh = r.fresh_base(unit, base)
        except Exception as error:  # noqa: BLE001
            # Asking the forge is the network too: a unit that passed review is
            # not failed because the host did not answer.
            self.say(f"could not ask the forge for the base, going on with {base}: {error}")
            fresh = base
        if fresh != base:
            self.say(f"base is now {fresh}, not {base}")
            base = fresh
        try:
            # Without the resolver: a resolution here would run outside the
            # usage gate and leave the branch rewritten without review knowing.
            moved = r.restack_onto(
                tree=self.tree(),
                branch=branch_name(unit),
                base=local_ref(base, repo=unit.repo),
                unit=unit,
                resolve=False,
            )
        except (AgentRateLimited, AgentInterrupted):
            raise
        except Exception as error:  # noqa: BLE001
            return self.rebase(state, f"moving onto {base} needed resolution: {error}", base=base)
        if moved is not None:
            if moved.conflict or moved.resolved:
                return self.rebase(state, f"moving onto {base} needed resolution", base=base)
            self.say(f"moved onto {base} cleanly; tier 1 again")
        return {"base": base, "moved": moved is not None}

    def push(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        # The rule, checked where it matters: only the commit review approved leaves.
        head, approved = r.head(tree), r.store.get(unit.id).approved
        if not state.spent and (not approved or head != approved):
            return self.stop(
                f"refusing to push {head[:9] or '?'}: review approved "
                f"{approved[:9] or 'nothing'} on this branch"
            )
        branch = branch_name(unit)
        # Always through `push`, where a branch the host moved is caught; pushing
        # a commit the remote already has changes nothing.
        try:
            sha = r.push(branch, cwd=tree)
        except HostMoved as error:
            if not state.spent:
                # Not pushed: the tree holds the host's head, and review has to pass it first.
                self.say(f"not pushed: {error}")
                return self.hold(
                    PLANNED,
                    f"not pushed: {error}",
                    f"re-reviewing: {error}",
                    cause=Cause.RESTACK_DEFERRED,
                )
            # The adoption is recorded, so a second push holds the lease: this
            # path pushes unapproved work for a person by design.
            self.say(f"{error} — pushing again")
            sha = r.push(branch, cwd=tree)
        self.say(f"pushed {branch} at {sha[:9]}")
        if state.spent:
            return {}
        # Only now, with the push confirmed: a follow-up recorded ahead of it
        # would describe work that never left the machine.
        if state.deferred:
            r.record_follow_ups(unit, state.deferred)
            return {"deferred": ()}
        return {}

    def open_pr(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, base = self.tree(), state.base or self.base
        stored = r.store.get(unit.id)
        # A re-run asks again: `open_pr` finds the branch's pull request and updates it.
        body = partial(
            build_pr_body,
            stored,
            graph=self.graph or [stored],
            base=base,
            tier2_snapshot=state.snapshot or None,
            open_points=stored.feedback if state.spent else None,
            follow_ups=r.follow_ups_for(unit) or None,
            linear=r.linear(tree, local_ref(base, repo=unit.repo)),
            limit=forges.for_repo(unit.repo)[0].description_limit,
        )
        try:
            pr = r.open_pr(
                unit,
                body=body(stacks=False),
                stacked_body=body(stacks=True),
                base=base,
                cwd=tree,
            )
        except BaseMissing as error:
            # Deleted between the check and the call, most often by its merge:
            # ask again, and go on from whatever it is now.
            try:
                base = r.fresh_base(unit, base)
            except Exception as asked:  # noqa: BLE001
                self.say(f"could not ask the forge for the base: {asked}")
            return self.rebase(
                state, str(error), base=base, lead="base gone before its pull request"
            )
        if state.spent:
            note = f"rounds spent with work outstanding: {' '.join(stored.feedback.split())[:300]}"
            return self.hold(
                HELD,
                note,
                f"rounds spent, held as #{pr}",
                cause=Cause.NEEDS_HUMAN,
                pr=pr,
                held_by=HeldBy.REVIEW,
            )
        # Cleared only now, after the work is pushed and the pull request
        # updated: left in place, the next tick would rework the unit again for
        # a comment it has already answered.
        sha = r.head(tree)
        # After the push, never before: a status for a commit the host has not
        # seen is rejected.
        if unit.tier == "tier2":
            r.post_status(sha, True)
        # What the host did not take stays owed, for the next pass to post.
        unposted = tuple(
            left
            for answer in state.pending_replies
            if (left := r.reply(repo=unit.repo, pr=pr, answer_text=answer, sha=sha))
        )
        if state.given_comments:
            r.record_given(unit.repo, pr, list(state.given_comments))
        if state.had_feedback:
            r.store.set_feedback(unit.id, "")
        r.store.set_state(unit.id, IN_REVIEW, pr=pr)
        if r.store.get(unit.id).predecessor_note:
            r.store.set_predecessor_note(unit.id, "")
        # Done means through the loop, verified and pushed.
        r.mark_tasks(unit, done=True)
        self.say(f"in review: PR #{pr}")
        return {
            "status": RunStatus.OPEN,
            "detail": f"opened #{pr}",
            "pr": pr,
            # Said, except what the host did not take: the loop that asked is over.
            "pending_replies": unposted,
            "person_comments": "",
            "seen_comments": None,
            "given_comments": (),
            "review_rounds": (),
        }

    def await_review(self, state: UnitRun) -> Update:
        """Wait for the forge: the interrupt holds no lock and no slot, and the
        event that ends it is acted on by `resume_unit`, under the branch's lock."""
        event = ResumeEvent.model_validate(interrupt({"wait": "review"}))
        return self.on_event(state, event)

    def held(self, state: UnitRun) -> Update:
        """Wait for a person: a requeue, a merge or a close."""
        event = ResumeEvent.model_validate(interrupt({"wait": "held"}))
        return self.on_event(state, event)

    def on_event(self, state: UnitRun, event: ResumeEvent) -> Update:
        """What an event does to a unit that was waiting: the store and the
        state the routers read. Where it goes next is `after_await_review`
        and `after_held`."""
        r, unit = self.runner, self.unit
        self.say(f"{event.kind.value}: {event.reason or 'no reason given'}")
        if state.status is RunStatus.HELD and event.kind in (
            EventKind.REWORK,
            EventKind.HOLD,
            EventKind.BASE_MOVED,
        ):
            # A person has the unit: nothing automatic touches it again.
            return {"event": None}
        update: Update = {"event": event}
        if event.kind is EventKind.REWORK:
            r.store.set_feedback(
                unit.id,
                event.feedback or event.reason,
                from_person=event.from_person,
                source=event.feedback_source,
            )
            r.store.set_state(
                unit.id, RUNNING, note=f"rework requested: {event.reason}", cause=Cause.REWORK
            )
            update.update(self.fresh_run(had_feedback=True))
            if pr := r.store.get(unit.id).pr:
                # Recorded here, not when the node runs: a comment posted while the thread
                # waits for a slot is new.
                if event.from_person:
                    # Only what the dispatch built the feedback from was given to the agent:
                    # a comment posted since its reads is new, and goes back to the rework.
                    update["seen_comments"] = given = event.comment_ids or ()
                    update["given_comments"] = given
                else:
                    # A CI log or a conflict text gives the agent no comment, so none of
                    # those on the pull request was given; they were answered before.
                    update["seen_comments"] = self.covered(pr)
        elif event.kind is EventKind.ADOPTED:
            # A chat's commit is on the branch: nothing earlier is approved, and the checks
            # start with a fix budget of their own. The recorded node start is the chat's now.
            r.store.set_state(
                unit.id,
                RUNNING,
                note=f"adopted: {event.reason or 'a commit from a chat'}",
                cause=Cause.ADOPTED,
            )
            update.update(self.fresh_run())
            update.update({"spent": False, "adopted": True, "running_node": ""})
        elif event.kind is EventKind.HOLD:
            current = r.store.get(unit.id)
            if held_for_its_own_reason(current):
                # Held for a reason of its own (the toolchain, the review loop):
                # the label did not make it, so its removal must not undo it. A
                # depth hold a merge would free is taken over instead.
                self.say(f"already held by {held_cause(current)}, as it stands")
                return {"event": None}
            if not current.held_by_the_label:
                r.store.set_state(
                    unit.id,
                    HELD,
                    note=takeover_note(current, event.reason),
                    held_by=HeldBy.REVIEWER,
                    held_base=current.held_base,
                    cause=Cause.REVIEWER_HOLD,
                )
            update.update({"status": RunStatus.HELD, "detail": event.reason or "held"})
        elif event.kind is EventKind.RELEASE:
            current = r.store.get(unit.id)
            if not current.held_by_the_label:
                self.say("not held by the label, nothing to release")
                return {"event": None}
            if restore_depth_hold(r.store, current):
                limits = active().limits
                cap = limits.stack_depth_rebase_cap
                cap = limits.stack_depth_build_cap if cap is None else cap
                depth = depth_of(current, r.store.all())
                if depth > cap:
                    self.say(f"held for depth again: depth {depth} is beyond the rebase cap {cap}")
                    return {"event": None}
                # A merge during the label brought it within the cap: the run
                # takes up at `prepare`, which moves it onto its base.
                r.store.set_state(
                    unit.id,
                    RUNNING,
                    note=f"depth {depth} is within the cap",
                    cause=Cause.RELEASED,
                )
                update.update(self.fresh_run())
                update.update(
                    {
                        "event": ResumeEvent(
                            kind=EventKind.REQUEUE,
                            requeue=RequeueReason.RELEASED,
                            reason="released",
                        )
                    }
                )
                update["base"] = ""
                return update
            r.store.set_state(unit.id, IN_REVIEW, note="hold label removed", cause=Cause.RELEASED)
            update.update({"status": RunStatus.OPEN, "detail": "released"})
        elif event.kind in (EventKind.BASE_MOVED, EventKind.REQUEUE):
            if event.requeue is RequeueReason.RESTART:
                r.store.set_feedback(unit.id, "")
                update["review_rounds"] = ()
            head = ""
            if resumes_parked(state, event):
                # Read before the store moves: a tree still dirty keeps the unit held,
                # waiting, with no event for the router to act on.
                try:
                    head = r.head(self.tree())
                except DirtyWorktree as error:
                    return {**self.park(error), "event": None}
            # Running, so the tick resumes the thread at `prepare` in a slot.
            r.store.set_state(
                unit.id,
                RUNNING,
                note=f"{event.kind.value}: {event.reason or 'no reason given'}",
                cause=Cause.BASE_CHANGED if event.kind is EventKind.BASE_MOVED else Cause.REQUEUED,
            )
            if resumes_parked(state, event):
                # Parked for its tree and cleaned: the node that parked goes next with its
                # inputs as they stood (a rework's feedback, the commits already made).
                # The head is the tip after the clean: a person who committed the stray
                # edits moved it, and those commits are not the parked node's work.
                update.update(
                    {
                        "head": head,
                        "status": None,
                        "detail": "",
                        "held": "",
                        "hold_state": "",
                        "hold_note": "",
                        "stopped": "",
                    }
                )
            else:
                update.update(self.fresh_run())
            if event.kind is EventKind.BASE_MOVED:
                # The run takes the base the store names when the tick starts
                # it: the one `verify_base` last recorded is the old one.
                update["base"] = ""
        else:
            update["detail"] = event.kind.value
        return update

    @staticmethod
    def fresh_run(*, had_feedback: bool = False) -> Update:
        """A thread taking up work again: what the last run ended on is not this run's."""
        return {
            "verdict": None,
            "stopped": "",
            "status": None,
            "detail": "",
            "review_round": 0,
            "fix_rounds": 0,
            "checks_ok": False,
            "produced_nothing": False,
            "moved": False,
            "head_approved": False,
            "pushed_head": False,
            "opened": False,
            "head": "",
            "seen_comments": None,
            "given_comments": (),
            "comments_pending": False,
            "had_feedback": had_feedback,
            "held": "",
            "hold_state": "",
            "hold_note": "",
            "adopted": False,
        }

    def failed(self, state: UnitRun) -> Update:
        outcome = self.runner.fail(self.unit, state.stopped)
        return {"status": outcome.status, "detail": outcome.detail}


def _listed(paths: tuple[str, ...]) -> str:
    """Paths for a prompt or a hold, the first few and a count of the rest."""
    shown = ", ".join(paths[:LEFTOVER_PATHS_SHOWN])
    more = len(paths) - LEFTOVER_PATHS_SHOWN
    return f"{shown} (and {more} more)" if more > 0 else shown


def _round(node: Node, state: UnitRun) -> int:
    """The round a step is in, for the steps that go in rounds; 0 for the rest."""
    if node is Node.REVIEW:
        return state.review_round + 1
    if node in (Node.CHECKS, Node.FIX_CHECKS):
        return state.fix_rounds + 1
    if node is Node.REWORK:
        return state.review_round
    return 0


def halted(state: UnitRun) -> Node | None:
    """Where a run that has to stop goes, whatever node it stopped in."""
    if state.held:
        return Node.HELD
    if state.stopped:
        return Node.FAILED
    return None


def after_prepare(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.conflict:
        return Node.ADAPT
    if state.pushed_head and (
        not state.opened or (state.pending_replies and not state.had_feedback)
    ):
        # The work is approved and on the remote: only the pull request step is left.
        # Feedback saved after the pull request was opened is still to be reworked.
        return Node.OPEN_PR
    if state.had_feedback:
        return Node.REWORK
    if not state.base_commits:
        return Node.TESTS
    if state.head_approved:
        # Review approved exactly this commit: nothing was written since.
        return Node.TIER2 if state.tier2 else Node.VERIFY_BASE
    return Node.CHECKS


def after_implement(state: UnitRun) -> Node:
    return halted(state) or (Node.TIER1 if state.produced_nothing else Node.CHECKS)


def after_checks(state: UnitRun) -> Node:
    return halted(state) or (Node.REVIEW if state.checks_ok else Node.FIX_CHECKS)


def after_fix_checks(state: UnitRun) -> Node:
    return halted(state) or Node.CHECKS


def after_review(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.spent:
        return Node.PUSH
    if state.verdict is not Verdict.APPROVED:
        return Node.REWORK
    return Node.TIER2 if state.tier2 else Node.VERIFY_BASE


def after_rework(state: UnitRun) -> Node:
    return halted(state) or (Node.TIER1 if state.produced_nothing else Node.CHECKS)


def after_tier1(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    if state.produced_nothing:
        return Node.SATISFIED
    if state.moved:
        # verify_base already moved the unit onto the base: nothing left to check there.
        return Node.TIER2 if state.tier2 else Node.NEW_COMMENTS
    return Node.VERIFY_BASE


def after_tier2(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    return Node.NEW_COMMENTS if state.moved else Node.VERIFY_BASE


def after_verify_base(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    return Node.TIER1 if state.moved else Node.NEW_COMMENTS


def after_new_comments(state: UnitRun) -> Node:
    return halted(state) or (Node.REWORK if state.comments_pending else Node.PUSH)


def after_push(state: UnitRun) -> Node:
    return halted(state) or Node.OPEN_PR


def after_open_pr(state: UnitRun) -> Node:
    return halted(state) or (Node.PREPARE if state.restack else Node.AWAIT_REVIEW)


def after_await_review(state: UnitRun) -> Node | str:
    kind = state.event.kind if state.event else None
    if kind is EventKind.REWORK:
        return Node.REWORK
    if kind in (EventKind.BASE_MOVED, EventKind.REQUEUE):
        return Node.PREPARE
    if kind is EventKind.ADOPTED:
        return Node.CHECKS
    if kind is EventKind.HOLD:
        return Node.HELD
    if kind in (EventKind.MERGED, EventKind.CLOSED):
        return END
    return Node.AWAIT_REVIEW


def resumes_parked(state: UnitRun, event: ResumeEvent) -> bool:
    """A requeue of a unit parked at a node goes back to that node; a restart begins again."""
    return (
        event.kind is EventKind.REQUEUE
        and event.requeue is not RequeueReason.RESTART
        and bool(state.parked_node)
    )


def after_held(state: UnitRun) -> Node | str:
    kind = state.event.kind if state.event else None
    if kind is EventKind.REQUEUE:
        if state.event and resumes_parked(state, state.event):
            return Node(state.parked_node)
        return Node.PREPARE
    if kind is EventKind.ADOPTED:
        return Node.CHECKS
    if kind is EventKind.RELEASE:
        return Node.AWAIT_REVIEW
    if kind in (EventKind.MERGED, EventKind.CLOSED):
        return END
    return Node.HELD


# Each node's router and the nodes it may name, which compiling checks.
Target = Node | str
PREPARED: tuple[Target, ...] = (
    Node.HELD,
    Node.FAILED,
    Node.ADAPT,
    Node.REWORK,
    Node.CHECKS,
    Node.TESTS,
    Node.TIER2,
    Node.VERIFY_BASE,
    Node.OPEN_PR,
)
ROUTES: Mapping[Node, tuple[Callable[[UnitRun], Target], tuple[Target, ...]]] = {
    Node.PREPARE: (
        after_prepare,
        PREPARED,
    ),
    Node.ADAPT: (
        after_prepare,
        PREPARED,
    ),
    Node.IMPLEMENT: (after_implement, (Node.HELD, Node.TIER1, Node.CHECKS)),
    Node.CHECKS: (after_checks, (Node.HELD, Node.FAILED, Node.REVIEW, Node.FIX_CHECKS)),
    Node.FIX_CHECKS: (after_fix_checks, (Node.HELD, Node.FAILED, Node.CHECKS)),
    Node.REVIEW: (
        after_review,
        (Node.HELD, Node.FAILED, Node.PUSH, Node.TIER2, Node.VERIFY_BASE, Node.REWORK),
    ),
    Node.REWORK: (after_rework, (Node.HELD, Node.TIER1, Node.CHECKS)),
    Node.TIER1: (
        after_tier1,
        (
            Node.HELD,
            Node.FAILED,
            Node.PREPARE,
            Node.SATISFIED,
            Node.TIER2,
            Node.VERIFY_BASE,
            Node.NEW_COMMENTS,
        ),
    ),
    Node.TIER2: (
        after_tier2,
        (Node.HELD, Node.FAILED, Node.PREPARE, Node.VERIFY_BASE, Node.NEW_COMMENTS),
    ),
    Node.VERIFY_BASE: (
        after_verify_base,
        (Node.HELD, Node.FAILED, Node.PREPARE, Node.TIER1, Node.NEW_COMMENTS),
    ),
    Node.NEW_COMMENTS: (after_new_comments, (Node.HELD, Node.FAILED, Node.REWORK, Node.PUSH)),
    Node.PUSH: (after_push, (Node.HELD, Node.FAILED, Node.OPEN_PR)),
    Node.OPEN_PR: (after_open_pr, (Node.HELD, Node.PREPARE, Node.AWAIT_REVIEW)),
    Node.AWAIT_REVIEW: (
        after_await_review,
        (Node.REWORK, Node.PREPARE, Node.CHECKS, Node.HELD, Node.AWAIT_REVIEW, END),
    ),
    Node.HELD: (
        after_held,
        (Node.PREPARE, Node.CHECKS, Node.AWAIT_REVIEW, Node.HELD, END, *sorted(PARKABLE)),
    ),
}
