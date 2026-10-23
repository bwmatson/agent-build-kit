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
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.graph import END
from langgraph.types import interrupt

from agent_build_kit import claude_account, forges, profiles, telemetry
from agent_build_kit.budget import cut_head
from agent_build_kit.config import (
    E2eBeforeMerge,
    active,
    active_root,
    ceilings_in_effect,
    e2e_before_merge,
    models,
)
from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.graph import check_loop
from agent_build_kit.graph.check_loop import CheckLoop, CheckParked
from agent_build_kit.graph.state import (
    RESUME_IMPLEMENT,
    RESUME_TESTS,
    AgentSession,
    EventKind,
    Node,
    ResumeEvent,
    SessionRole,
    UnitRun,
    Verdict,
)
from agent_build_kit.installation import Installation, changes_dir_under
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline import audit_record, environment, spans, spec_snapshot
from agent_build_kit.pipeline.agent_commands import commands_note
from agent_build_kit.pipeline.call_record import call_recorder
from agent_build_kit.pipeline.changelog_convention import changelog_note
from agent_build_kit.pipeline.check_failures import failed_check
from agent_build_kit.pipeline.commit_body import commit_body
from agent_build_kit.pipeline.commit_order import (
    CODE_PREFIX,
    TESTS_PREFIX,
    GroupProgress,
    cherry_pick,
    group_progress,
    recorded_built,
    superseded_pairs,
)
from agent_build_kit.pipeline.e2e import NO_TEST_RAN, E2eVerdict
from agent_build_kit.pipeline.e2e_schedule import is_scheduled, scheduled_split
from agent_build_kit.pipeline.e2e_scope import is_product_path, is_test_path
from agent_build_kit.pipeline.events import (
    held_cause,
    held_for_its_own_reason,
    restore_depth_hold,
    takeover_note,
)
from agent_build_kit.pipeline.flakes import FlakeFound, waiting_note
from agent_build_kit.pipeline.gateway_usage import attribution
from agent_build_kit.pipeline.manual_steps import unmet_steps
from agent_build_kit.pipeline.metric_records import emit_metric
from agent_build_kit.pipeline.outside_commits import outside_commits_note
from agent_build_kit.pipeline.pr_body import build_pr_body, satisfied_reason
from agent_build_kit.pipeline.pr_replies import parse_answer
from agent_build_kit.pipeline.product_defect import DefectRefused, read_product_defect
from agent_build_kit.pipeline.restack import RESOLVER_TOOLS, BranchMoved, HostMoved
from agent_build_kit.pipeline.review_classes import class_of
from agent_build_kit.pipeline.review_paths import is_protected
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import (
    ADAPT_CONTINUATION,
    ADAPT_FOLLOWUP_PROMPT,
    ADAPT_PROMPT,
    CHECKS_CONTINUATION,
    CHECKS_PROMPT,
    E2E_SCOPE_NOTE,
    IMPLEMENTATION_CONTINUATION,
    IMPLEMENTATION_PROMPT,
    LEFTOVERS_NOTE,
    MOVED_NOTE,
    PREDECESSOR_NOTE,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    SCOPE_FEEDBACK,
    STUB_CHECKS_PROMPT,
    STUBBED_TESTS_FINISH,
    TEST_ONLY_TESTS_FINISH,
    TESTS_FINISH,
    TESTS_PROMPT,
    TRIED_NOTE,
    UNIT_TEST_FAILED,
    WHOLE_ASK,
    Escalation,
    GroupStep,
    Restacked,
    RunStatus,
    UnitOutcome,
    UnitRunner,
    Weighed,
    check_test_decisions,
    escalates,
    parse_test_decisions,
    person_guidance,
    tests_needing_decision,
    with_response,
)
from agent_build_kit.pipeline.unit_store import (
    Cause,
    ClosePending,
    E2eState,
    FeedbackSource,
    HeldBy,
    RequeueReason,
    StoredSplitRequest,
    StoredUnit,
    guidance_excerpt,
)
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    SATISFIED,
    Member,
    Unit,
    UnitState,
    branch_name,
    depth_of,
    local_ref,
)
from agent_build_kit.pipeline.untouched_failures import feedback_snapshot
from agent_build_kit.pipeline.untouched_failures import waiting_note as preexisting_waiting_note
from agent_build_kit.pipeline.usage_guard import ask_before_call, starting
from agent_build_kit.pipeline.usage_ledger import (
    session_cumulative,
)
from agent_build_kit.pipeline.verdict import (
    GateResult,
    GroupText,
    ReviewTier,
    SplitRequest,
    TierVerdict,
    VerdictFacts,
)
from agent_build_kit.pipeline.verdict_record import (
    VERDICTS,
    latest_verdict,
    mark_brief,
    record_verdict,
    recorded_history,
)
from agent_build_kit.pipeline.work_graph import group_sections
from agent_build_kit.pipeline.workspaces import DirtyWorktree, superseded_ref
from agent_build_kit.profiles.base import stubbed_build
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentResult,
    NetworkUnavailable,
    ServiceUnavailable,
    SessionUnavailable,
)

Update = dict[str, Any]

# What a trip back through `prepare` starts over from; the rest of the state is
# what that trip recomputes.
FRESH: Update = {
    "restack": False,
    "moved": False,
    "moved_from": "",
    "conflict": None,
    "verdict": None,
    "fix_rounds": 0,
    "review_round": 0,
    "spent": False,
    "checks_ok": False,
    "produced_nothing": False,
    "snapshot": "",
    "e2e_ran_none": False,
}

# Paths of uncommitted work named in a prompt or a hold; the rest are counted.
LEFTOVER_PATHS_SHOWN = 40
ACCOUNT_LIMIT = 2000  # characters of the builder's account a recorded group keeps
ACCOUNT_HEADING = "Already built, the builder's account:"
NO_NEW_TESTS = "This group adds no new tests: the tests it needs already exist on the branch."
TESTS_ALREADY_PASS = (
    "The tests for this group pass without further implementation: "
    "the implementation already exists."
)

# Lines of a failing e2e-test's report written to the run log.
E2E_LOG_TAIL = 40

# The nodes a unit is held before, at the boundary, when its upstream went back
# for rework or its base moved: the ones that start work or leave the machine.
GATED = frozenset({Node.IMPLEMENT, Node.FIX_CHECKS, Node.REVIEW, Node.REWORK, Node.VERIFY_BASE})
# The nodes that start an agent: each asks the usage guard first.
AGENT_NODES = frozenset(
    {
        Node.TESTS,
        Node.IMPLEMENT,
        Node.FIX_CHECKS,
        Node.FIX_STUB_CHECKS,
        Node.REVIEW,
        Node.REWORK,
        Node.ADAPT,
    }
)
# The nodes a unit with a step only a person can do is parked before: each agent step, and the
# two that put the branch on the host.
MANUAL_GATED = AGENT_NODES | {Node.PUSH, Node.OPEN_PR}
# The agent nodes that edit the tree: a dirty tree left by a killed run of one of
# these is that node's own work to carry on from. Review writes nothing.
EDITING_NODES = frozenset(
    {Node.TESTS, Node.IMPLEMENT, Node.FIX_CHECKS, Node.FIX_STUB_CHECKS, Node.REWORK, Node.ADAPT}
)
# The nodes a park records and a requeue goes back to, with their inputs as they stood:
# `prepare` would route on the branch alone and lose what the node was to do.
PARKABLE = EDITING_NODES | {Node.REVIEW}
# The conversation each agent node speaks in. A node gets a role of its own only
# when it must not share context with the others (a reviewer with the author).
SESSION_ROLES: dict[Node, SessionRole] = {
    Node.TESTS: SessionRole.BUILD,
    Node.IMPLEMENT: SessionRole.BUILD,
    Node.FIX_CHECKS: SessionRole.BUILD,
    Node.FIX_STUB_CHECKS: SessionRole.BUILD,
    Node.REWORK: SessionRole.BUILD,
    Node.ADAPT: SessionRole.BUILD,
    Node.RESTACK: SessionRole.BUILD,
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
        # What `prepare` found uncommitted from a run stopped in the stub check loop, for the
        # fix that follows it to tell its agent about.
        self._stub_leftovers: tuple[str, ...] = ()
        # The last session an agent call of the running node ended in:
        # (id, runtime, model, the session's cumulative cost after the call).
        self._ended: tuple[str, str, str, float | None] | None = None
        # The hash of the spec copies taken when the node's last agent call was prompted.
        self._spec_taken = ""
        # The cumulative cost of each session the running node's calls ended, so a follow-up
        # in the same node starts from the call before it.
        self._totals: dict[str, float] = {}

    def work(self) -> dict[Node, Callable[[UnitRun], Any]]:
        """Each node's body, wrapped in its span and run off the event loop."""
        bodies = {
            Node.PREPARE: self.prepare,
            Node.TESTS: self.tests,
            Node.IMPLEMENT: self.implement,
            Node.CHECKS: self.checks,
            Node.FIX_CHECKS: self.fix_checks,
            Node.STUB_CHECKS: self.stub_checks,
            Node.FIX_STUB_CHECKS: self.fix_stub_checks,
            Node.REVIEW: self.review,
            Node.REWORK: self.rework,
            Node.ADAPT: self.adapt,
            Node.UNIT_TEST: self.unit_test,
            Node.E2E: self.e2e,
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

    def _round_cause(self, node: Node) -> str:
        """Why a review round runs, for its span: `conflict` for an adapt or a rework a
        restack started, `check` for a failed check's, `review` for the rest; empty for a
        node that is not a round. Only a rework reads the unit's record, and a record that
        cannot be read is not the node's failure."""
        if node is Node.ADAPT:
            return "conflict"
        if node in (Node.FIX_CHECKS, Node.FIX_STUB_CHECKS):
            return "check"
        if node is not Node.REWORK:
            return ""
        try:
            source = self.runner.store.get(self.unit.id).feedback_source
        except Exception:  # noqa: BLE001 — a span's cause is never a run's to lose
            return "review"
        match source:
            case FeedbackSource.CONFLICT:
                return "conflict"
            case (
                FeedbackSource.CI
                | FeedbackSource.UNIT_TEST
                | FeedbackSource.E2E
                | FeedbackSource.SCOPE
            ):
                return "check"
            case _:
                return "review"

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
            # Before the body: a rework clears the feedback it acts on.
            cause = self._round_cause(node)
            with span as current:
                self._node = node.value
                self._ended = None
                self._spec_taken = ""
                self._totals = {}
                context = spans.current_unit.set(
                    (self.unit.id, self.unit.change, node.value, _round(node, state))
                )
                self.say("started")
                try:
                    # Off the loop: the callables block on agents and git.
                    update = await asyncio.to_thread(self._step, node, body, state)
                    # A step that completes ends the row of parkings on the service's status.
                    self.runner.store.reset_service_attempts(self.unit.id)
                    if update.get("stopped"):
                        # The run ends `failed` for this, and the record names the step.
                        self.record_step(node)
                    outcome = (
                        UnitOutcome(update["status"]) if update.get("status") else UnitOutcome.OK
                    )
                    # The node is done, and with it the session it was in.
                    done: Update = {
                        # A thread saved before the field was renamed comes back with it unset,
                        # and a resume may skip `prepare`, the only other place that sets it.
                        **self._restored_e2e(state, update),
                        **update,
                        **self._sessions_after(node, state, update),
                        "session_id": "",
                        "running_node": "",
                    }
                    # The waiting node's own return must not clear what a requeue routes on.
                    if node is Node.HELD:
                        return done
                    # A park before a node names it, which a release goes back to.
                    return {**done, "parked_node": update.get("parked_node", "")}
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
                except (NetworkUnavailable, ServiceUnavailable):
                    # Not a failure, but the step it stopped on is what the unit resumes at.
                    outcome = UnitOutcome.INTERRUPTED
                    self.record_step(node)
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
                        cause=cause,
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

    def _restored_e2e(self, state: UnitRun, update: Update) -> Update:
        """The `e2e` flag from the unit's kind, when the thread lacks it."""
        if state.e2e or "e2e" in update or self.unit.tier != TestTier.E2E_TEST:
            return {}
        return {"e2e": True, "e2e_deferred": self.e2e_deferred()}

    def e2e_deferred(self) -> bool:
        """Whether this unit's repo leaves e2e-test to verify, after the merge."""
        config = active()
        repo = config.repos.get(self.unit.repo)
        return repo is not None and (
            e2e_before_merge(repo, config.global_limits) is E2eBeforeMerge.DEFERRED
        )

    def account_key(self) -> str:
        """The key of the account this unit's calls run on: its directory, never empty. A stored
        session with an empty key was made before keys were recorded, so it is not compared."""
        return str(claude_account.home(self.runner.account))

    def _under_account(self) -> str:
        """Names the Claude Code account in a line about a session `claude` cannot find, when one
        is set: a stored session belongs to the account it was begun under."""
        account = claude_account.account_key(self.runner.account)
        return f", under the account {account}" if account else ""

    def record_step(self, node: Node) -> None:
        """Name `node` as the step the unit is failing in; never raises."""
        try:
            self.runner.store.record_step(self.unit.id, node.value)
        except Exception as recording:  # noqa: BLE001
            self.say(f"could not record the failing step — {recording}")

    def _sessions_after(self, node: Node, state: UnitRun, update: Update) -> Update:
        """The role's session as the node leaves it, and the model the build began on."""
        if node is Node.PREPARE and self._ended is not None:
            # Its restack asked the agent: the session it left is the restack step's.
            node = Node.RESTACK
            update = {**update, "head": self.runner.head(self.tree())}
        if (role := SESSION_ROLES.get(node)) is None:
            return {}
        if self._ended is None:
            # A call killed before it reported its result leaves no session to record, and
            # the role's earlier one no longer holds what the node did.
            if state.session_id and role in state.sessions:
                return {"sessions": {k: v for k, v in state.sessions.items() if k != role}}
            return {}
        session_id, runtime, model, cumulative = self._ended
        head = update["head"] if "head" in update else state.head
        session = AgentSession(
            session_id=session_id,
            runtime=runtime,
            model=model,
            node=node,
            round=_round(node, state),
            head=head,
            cumulative_usd=cumulative,
            account=self.account_key(),
            spec=self._spec_taken,
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
        with starting(self.unit.id):
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
        if node in MANUAL_GATED and (waiting := self.manual_wait(node)):
            return waiting
        gated = (
            node in GATED
            or (node is Node.UNIT_TEST and state.produced_nothing and not state.moved)
            or (node is Node.PUSH and state.spent)
            or (node is Node.E2E and not state.moved)
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

    def manual_wait(self, node: Node) -> Update | None:
        """Park the unit, planned, before `node` while a step only a person can do is unmet,
        declared by its groups or raised by a build. A release goes back to `node`. None when
        no step is unmet."""
        unmet = unmet_steps(self.runner.store.get(self.unit.id))
        if not unmet:
            return None
        names = ", ".join(step.slug for step in unmet)
        note = f"waiting for manual step {names} before {node.value}"
        self.record_step(node)
        return {
            **self.hold(PLANNED, note, note, cause=Cause.MANUAL_STEP),
            "parked_node": node.value,
        }

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
            "hold_state": state.value,
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
        if state.session_id and state.session_account not in ("", self.account_key()):
            self.say(
                f"session {state.session_id} was made under another account; "
                "running the node from its start in a new session"
            )
            state = state.model_copy(update={"session_id": ""})
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
            self._save_spec()
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
                    f"session {state.session_id} cannot be continued "
                    f"({error}{self._under_account()}); "
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
                    f"the {SESSION_ROLES[Node(self._node)]} session cannot be continued "
                    f"({why}{self._under_account()}); "
                    "running the node from its start in a new session"
                )
        if self._leftovers:
            self._resuming_over_leftovers("new")
            note = LEFTOVERS_NOTE.format(paths=_listed(self._leftovers))
            args = (f"{args[0]}\n\n{note}", *args[1:])
        self._save_spec()
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
        if session.account not in ("", self.account_key()):
            return None, "it was made under another account"
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
        if spec_note := self._spec_notice(SESSION_ROLES[Node(self._node)], session):
            follow_up = f"{spec_note}\n\n{follow_up}"
        self._save_spec()
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

    def _spec_places(self) -> tuple[Path, tuple[Member, ...], list[Path]] | None:
        """The state directory, and the unit's members with their change directories; None
        when no workspace is loaded."""
        if (root := active_root()) is None:
            return None
        members = self.unit.members()
        dirs = [Path(self.runner.change_dir(m.change)) for m in members]
        return Installation(active(), root).state_dir, members, dirs

    def _save_spec(self) -> None:
        """Keep the spec files the agent call about to be prompted reads; its hash is recorded
        on the session once the call ends."""
        role = SESSION_ROLES.get(Node(self._node))
        if role is None or (places := self._spec_places()) is None:
            return
        state_dir, members, dirs = places
        try:
            self._spec_taken = spec_snapshot.save(
                state_dir, self.unit.id, role.value, members, dirs
            )
        except (OSError, UnicodeDecodeError) as error:
            self.say(f"could not keep a copy of the spec — {error}")
            self._spec_taken = ""

    def _forget_spec(self) -> None:
        if places := self._spec_places():
            spec_snapshot.forget(places[0], self.unit.id)

    def _spec_notice(self, role: SessionRole, session: AgentSession) -> str:
        """What a resumed session is told about spec files edited since it last ran."""
        if (places := self._spec_places()) is None:
            return ""
        state_dir, members, dirs = places
        try:
            return spec_snapshot.notice(
                state_dir, self.unit.id, role.value, session.spec, members, dirs
            )
        except (OSError, UnicodeDecodeError) as error:
            self.say(f"could not compare the spec with its copy — {error}")
            return ""

    def _resuming_over_leftovers(self, session: str) -> None:
        if not self._leftovers:
            return
        self.say(
            f"resuming over uncommitted work in {len(self._leftovers)} file(s), session {session}"
        )
        telemetry.count("abk.leftovers.resumed", node=self._node, session=session)

    def _recorder(self, state: UnitRun, *, resumed: bool) -> Callable[..., None]:
        """What an agent call tells when it finishes: one line for the usage ledger."""
        unit = self.unit

        def ended(
            result: AgentResult, runtime: str, model: str | None, cumulative: float | None
        ) -> None:
            if result.session_id:
                self._ended = (result.session_id, runtime, model or "", cumulative)
                if cumulative is not None:
                    self._totals[result.session_id] = cumulative

        return call_recorder(
            self._node,
            unit=unit.id,
            change=unit.change,
            repo=unit.repo,
            tier=unit.tier,
            round=_round(Node(self._node), state),
            resumed=resumed,
            say=self.say,
            baseline=lambda session_id: self._baseline(state, session_id),
            after=ended,
        )

    def _baseline(self, state: UnitRun, session_id: str | None) -> float | None:
        """The session's cumulative cost before the call: from an earlier call of this node,
        the recorded session, or the ledger's last record of it."""
        if not session_id:
            return None
        if session_id in self._totals:
            return self._totals[session_id]
        if state.session_id == session_id:
            # A call cut off before its node finished has already written its figure to the
            # ledger, which the recorded session predates.
            if (written := session_cumulative(session_id)) is not None:
                return written
        for held in state.sessions.values():
            if held.session_id == session_id and held.cumulative_usd is not None:
                return held.cumulative_usd
        return session_cumulative(session_id)

    def record_check_failure(self, output: str, round: int) -> None:
        """Count a failed unit-test run of this unit, and keep it as a local metric record."""
        try:
            check = failed_check(output, self.unit.repo)
        except Exception:  # noqa: BLE001 — a record is never a run's to lose
            check = "unknown"
        emit_metric(
            "count",
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

    def environment_problem(self) -> str | None:
        """The output of the pipeline's failing `check`, None when it passes."""
        return environment.problem(self.runner.planning_repo)

    def worktree_fault(self, state: UnitRun) -> environment.WorktreeFault | None:
        """The repository's environment failing in this unit's worktree, None when healthy."""
        return environment.prepare_worktree(self.runner.repo_config, self.tree(), self.ref(state))

    def blocked(self, output: str) -> Update:
        """A unit the environment cannot run: failed with its own cause, nothing saved
        for an agent to fix."""
        self.say(output)
        return {
            **self.stop("the environment is unhealthy, so unit-test cannot run"),
            "blocked_by_environment": True,
        }

    def tree(self) -> Path:
        if self._tree is None:
            base = local_ref(self.base, repo=self.unit.repo)
            try:
                self._tree = self.runner.worktree(self.unit, base)
            except DirtyWorktree as dirty:
                if not (self._own or self._stopped_in_stub_loop()) or self._chat_changes():
                    raise
                self._tree = self.runner.worktree(self.unit, base, allow_dirty=True)
                self._leftovers = dirty.paths
                if not self._own:
                    self._stub_leftovers = dirty.paths
        return self._tree

    def _stopped_in_stub_loop(self) -> bool:
        """Whether the unit stopped in the stub check loop: the tests and stubs it left
        uncommitted in the tree are its own, to be fixed, not a person's to remove."""
        stored = self.runner.store.get(self.unit.id)
        return bool(stored.feedback) and stored.feedback_source is FeedbackSource.STUB_CHECKS

    def ref(self, state: UnitRun) -> str:
        return local_ref(state.base or self.base, repo=self.unit.repo)

    def outside_note(self, state: UnitRun, tree: Path) -> str:
        """The prompt part listing commits made to the branch outside the build session."""
        held = state.sessions.get(SessionRole.BUILD)
        repo = self.runner.repo_config
        return outside_commits_note(
            tree,
            self.ref(state),
            held.session_id if held else "",
            is_test=lambda path: is_test_path(path, repo),
        )

    @staticmethod
    def told(text: str, note: str) -> str:
        return f"{text}\n\n{note}" if note else text

    def scope_note(self) -> str:
        """What the first-build prompts of an `[e2e-test]` unit add: it holds tests and test
        support only; nothing for a unit of another tier."""
        return E2E_SCOPE_NOTE if self.unit.tier == TestTier.E2E_TEST else ""

    def prepare(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        branch = branch_name(unit)
        base = state.base or self.base
        saved = r.store.get(unit.id)
        feedback = saved.feedback
        r.store.set_state(unit.id, UnitState.RUNNING, branch=branch)
        # Made again: a trip back here may be onto a different base.
        self._tree = None
        tree, ref = self.tree(), self.ref(state)
        remembered: Update = {}
        # Taken before the restack and any adapt, so a base rewritten during
        # them is caught too: a parent restacked meanwhile keeps its name.
        start = r.base_tip(tree, ref)
        if state.base and not start:
            # A predecessor that merged takes its branch with it: the store's base is the
            # one to build on. Where that fails too, counting commits raises, as it must.
            self.say(f"the remembered base {state.base} no longer exists; using {self.base}")
            base, remembered = self.base, {"base": ""}
            state = state.model_copy(update=remembered)
            ref = self.ref(state)
            start = r.base_tip(tree, ref)
        if is_scheduled(unit.change):
            # No commits and no feedback to act on: the suite is its work, run on the
            # default branch as it is now, or on the fix it was released onto. The branch
            # never carries a commit of its own, so it is put on the base outright: a reused
            # worktree would otherwise run the commit of the last run again.
            r.fetch_quietly(unit)
            r.reset_to(tree, ref, f"refs/spec-driven/pre-scheduled/{unit.id}")
            start = r.base_tip(tree, ref)
            self.say(f"scheduled run on {base}: straight to e2e-test")
            return {**FRESH, **remembered, "start": start, "e2e": True, "scheduled": True}
        existing = r.branch_commits(tree, ref)
        if not existing and (parent := saved.split_from) and self.stubbed():
            self.reuse_superseded(parent, tree, ref)
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
                restacked = r.restack_onto(
                    tree=tree,
                    branch=branch,
                    base=ref,
                    unit=unit,
                    resolver=self.restack_resolver(state),
                )
            except (AgentRateLimited, AgentInterrupted, NetworkUnavailable, ServiceUnavailable):
                raise
            except BranchMoved as error:
                # Another writer moved the branch twice while its conflict was resolved: left
                # to a later tick, and not the once-per-run loop a moving base is given.
                note = (
                    f"restack onto {base} deferred: {error.branch} moved from "
                    f"{error.expected[:12]} to {error.found[:12]} while its conflict was "
                    "resolved, twice"
                )
                return {
                    **FRESH,
                    **remembered,
                    **self.hold(PLANNED, note, note, cause=Cause.RESTACK_DEFERRED),
                }
            except Exception as error:  # noqa: BLE001
                why = f"restack onto {base} conflicted: {error}"
                stored = r.store.get(unit.id)
                r.store.set_feedback(
                    unit.id,
                    f"{stored.feedback}\n\n{why}".strip(),
                    from_person=stored.feedback_from_person,
                    source=stored.feedback_source,
                )
                return {**FRESH, **remembered, **self.stop(why)}
            if restacked is not None:
                if not restacked.conflict and saved.sent_back_for_conflict:
                    # The move settled the conflict the feedback names: nothing to rework.
                    r.store.set_feedback(unit.id, "")
                    feedback = ""
                if restacked.conflict:
                    return {
                        **FRESH,
                        **remembered,
                        "start": start,
                        "head": r.head(tree),
                        "conflict": restacked,
                    }
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
            **remembered,
            # A person's note makes the run a rework as saved feedback does, once there is
            # work on the branch to rework; before that the build starts, tests first.
            **self.standing(existing, feedback or (saved.guidance if existing else ""), ref),
            "start": start,
            "e2e": unit.tier == TestTier.E2E_TEST,
            "e2e_deferred": unit.tier == TestTier.E2E_TEST and self.e2e_deferred(),
        }

    def reuse_superseded(self, parent_id: str, tree: Path, ref: str) -> None:
        """Pick the commit pair of each of this piece's groups from the superseded unit's kept
        branch onto the piece's branch, when that branch is exactly a pair per group of the unit;
        otherwise say once that the piece is built from scratch."""
        r = self.runner
        kept = superseded_ref(parent_id)
        try:
            parent = r.store.get(parent_id)
        except KeyError:
            return
        if git(tree, "rev-parse", "--verify", "-q", kept, check=False).returncode:
            return
        steps = r.group_steps(parent)
        found = superseded_pairs(
            tree, kept, ref, [s.title for s in steps], [s.test_only for s in steps]
        )
        if found is None:
            self.say(f"commits of {parent_id} not reused: they are not a pair for each group")
            return
        where = {(s.change_dir, s.number): index for index, s in enumerate(steps)}
        picked = 0
        for step in r.group_steps(self.unit):
            shas = found[where[(step.change_dir, step.number)]]
            if not cherry_pick(tree, shas, unit_id=self.unit.id):
                break
            picked += 1
        self.say(f"reused the commits of {picked} group(s) from {parent_id}")

    def resumed(self, existing: int, ref: str) -> Update:
        """In a stubbed build, the group the branch says is next: the first without its
        implementation commit, and whether its tests are already committed."""
        if not (existing and self.stubbed()):
            return {}
        steps = self.runner.group_steps(self.unit)
        progress = self.branch_progress(ref)
        if progress.done == len(steps) or not (progress.done or progress.tests_made):
            return {}  # finished, or not begun by this build: the path is the finished branch's
        return {
            "group": progress.done,
            "more_groups": progress.done + 1 < len(steps),
            "resume": RESUME_IMPLEMENT if progress.tests_made else RESUME_TESTS,
        }

    def standing(self, existing: int, feedback: str, ref: str) -> Update:
        """What the branch holds, which is what the path from here is chosen on."""
        r, unit = self.runner, self.unit
        head = r.head(self.tree())
        stored = r.store.get(unit.id)
        looping = bool(feedback) and stored.feedback_source is FeedbackSource.STUB_CHECKS
        return {
            "pushed_head": bool(existing) and head == stored.approved == stored.pushed,
            "opened": stored.pr is not None,
            "base_commits": existing,
            # Output saved by the stub check loop goes back to the loop, not to rework.
            "stub_loop": looping,
            "had_feedback": bool(feedback) and not looping,
            "resume": "",
            **self.resumed(existing, ref),
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
        tried = TRIED_NOTE.format(tried=cut_head(restacked.tried, 2000)) if restacked.tried else ""
        if r.head(tree) == state.head:
            r.reset_to(tree, ref, keep)
        # Otherwise a killed run already reset the branch: resetting again would
        # overwrite `keep` with the half-ported tree and lose the old work.
        answer = self.agent(
            r.run,
            ADAPT_PROMPT.format(
                commands=commands_note(r.repo_config),
                change_dir=change_dir,
                groups=groups,
                onto_unit=restacked.onto_unit,
                onto_intent=restacked.onto_intent,
                conflict=cut_head(restacked.conflict, 2000),
                tried=tried,
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
                conflict=cut_head(restacked.conflict, 2000),
                tried=tried,
                old_ref=keep,
                old_base=restacked.old_base,
                tests="\n".join(f"- `{name}`" for name in restacked.old_tests),
            ),
        )
        r.commit(f"adapt: {unit.title} onto {restacked.onto_unit}", cwd=tree, base=self.ref(state))
        self.forget_e2e_result()
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
        for _ in range(active().global_limits.max_adapt_rounds - 1):
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
        return {"conflict": None, **self.standing(r.branch_commits(tree, ref), feedback, ref)}

    def restack_resolver(self, state: UnitRun) -> Callable[..., None]:
        """What the restack asks to resolve a conflict: each call a call of the unit's build
        session on the rework model, recorded as the `restack` node. The first call continues
        the build session when there is one and reuse is on, and a later call the session the
        first ran in; `follow_up` is what a continuation says, the prompt what a new session is
        given."""
        held: AgentSession | None = None

        def resolve(prompt: str, *, cwd: Path, follow_up: str = "") -> None:
            nonlocal held
            # Asked like every other agent call, not left to the runtime's own refusal.
            ask_before_call(self.unit.id, self.runner.may_start, self.runner.resume_at)
            node, self._node = self._node, Node.RESTACK.value
            try:
                self.agent(
                    self.runner.run,
                    prompt,
                    cwd=cwd,
                    state=state,
                    model=models().rework,
                    follow_up=follow_up or prompt,
                    session=held,
                    # Not the build's tools: no git, so the pipeline alone moves the rebase.
                    tools=RESOLVER_TOOLS,
                    permission_mode="allowed_tools_only",
                )
            finally:
                self._node = node
            held = self.ported_session(self._ended, state, self.runner.head(cwd), node=Node.RESTACK)

        return resolve

    def ported_session(
        self,
        ended: tuple[str, str, str, float | None] | None,
        state: UnitRun,
        head: str,
        *,
        node: Node = Node.ADAPT,
    ) -> AgentSession | None:
        """The session a port or a restack's resolution ran in, as the calls that follow it
        continue it."""
        if ended is None:
            return None
        session_id, runtime, model, cumulative = ended
        return AgentSession(
            session_id=session_id,
            runtime=runtime,
            model=model,
            node=node,
            round=_round(node, state),
            head=head,
            cumulative_usd=cumulative,
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
        fault = self.worktree_fault(state)
        if fault is not None and fault.environment:
            return self.blocked(fault.output)
        stubbed = self.stubbed()
        if r.head(tree) != state.head:
            self.say("the tests commit is already on the branch")
        else:
            change_dir, groups = self.scope(state)
            build_boundary, _ = r.boundary_notes(unit, self.graph)
            self.say(f"write the tests ({models().implement})")
            prompt = TESTS_PROMPT.format(
                commands=commands_note(r.repo_config),
                guidance=person_guidance(r.store.get(unit.id).guidance),
                groups=groups,
                change_dir=change_dir,
                boundary=build_boundary,
                changelog=changelog_note(tree, r.repo_config),
                finish=self.tests_finish(state, stubbed=stubbed),
            )
            prompt = self.told(prompt, self.scope_note())
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            account = self.agent(r.run, prompt, cwd=tree, state=state, model=models().implement)
            if stubbed:
                # Committed by `stub_checks`, once the stubs and tests pass the static checks.
                step = self.group_step(state)
                kept = account if step is not None and step.test_only else ""
                return {"head": r.head(tree), "stub_loop": True, "tests_account": kept}
            self.apply_fixers()
            r.commit(self.message(TESTS_PREFIX, True, state), cwd=tree, base=self.ref(state))
        return {"head": r.head(tree), "stub_loop": False}

    def apply_fixers(self) -> None:
        """Run the profile's fixers over the unit's own files, with no agent, and log what they
        did; the files changed, or that they changed nothing when files were given. A pass given
        no files logs nothing."""
        result = self.runner.run_fixers(cwd=self.tree())
        if result.changed:
            self.say(f"fixers changed {len(result.changed)} file(s): {', '.join(result.changed)}")
        elif result.given:
            self.say("fixers changed nothing")
        if result.skipped:
            self.say(f"fixers skipped protected: {', '.join(result.skipped)}")
        if result.failed:
            self.say(f"fixers could not run: {'; '.join(result.failed)}")

    def tests_finish(self, state: UnitRun, *, stubbed: bool) -> str:
        """How the tests prompt ends; for a test-only group it says the group builds no
        implementation."""
        step = self.group_step(state)
        if step is not None and step.test_only:
            return TEST_ONLY_TESTS_FINISH
        return STUBBED_TESTS_FINISH if stubbed else TESTS_FINISH

    def stub_checks(self, state: UnitRun) -> Update:
        """Lint, format and types over what the test agent wrote, no test run; the tests commit
        is made once they pass."""
        r = self.runner
        tree = self.tree()
        self.say("static checks on the stubs and tests")
        result = check_loop.check_round(self, state, self.stub_check_loop(state))
        if not result.get("ok"):
            return result
        ref = self.ref(state)
        made = r.commit(self.message(TESTS_PREFIX, True, state), cwd=tree, base=ref)
        step = self.group_step(state)
        if step is None or not step.test_only:
            self.record_no_new_tests(state, ref, made)
            done: Update = {"head": r.head(tree), "stub_loop": False, "stub_rounds": 0}
            return {**done, "test_only_done": False}
        done = {"head": r.head(tree), "stub_loop": False, "stub_rounds": 0}
        # A test-only group's lone tests commit satisfies it: no implementation follows.
        if (stopped := self.record_built(state, ref, made, state.tests_account)) is not None:
            return stopped
        done["head"] = r.head(tree)
        commits = r.branch_commits(tree, ref)
        settled = self.settle_group(state, ref, commits)
        if "stopped" in settled:
            return settled
        return {**done, **settled, "test_only_done": True, "produced_nothing": commits == 0}

    def record_no_new_tests(self, state: UnitRun, ref: str, made: int) -> bool:
        """A group of a branch with commits whose tests step committed nothing gets an empty
        marked `test:`, so its implementation completes a pair. Not made when the group has a
        `test:` or a lone `feat:` already, or the earlier groups lack a pair."""
        r = self.runner
        tree = self.tree()
        if made or not r.branch_commits(tree, ref):
            return False
        progress = self.branch_progress(ref)
        if progress.done != state.group or progress.tests_made or progress.lone_feat:
            return False
        self.say("the group adds no new tests: an empty tests commit is recorded")
        r.commit_built(f"{self.message(TESTS_PREFIX, True, state)}\n\n{NO_NEW_TESTS}", cwd=tree)
        return True

    def fix_stub_checks(self, state: UnitRun) -> Update:
        self._leftovers = self._leftovers or self._stub_leftovers
        self._stub_leftovers = ()
        return check_loop.fix_round(self, state, self.stub_check_loop(state))

    def stub_check_loop(self, state: UnitRun) -> CheckLoop:
        """The stub loop's parameters for the shared routine: the static checks, no test run
        and no fix commit (the tests commit follows the pass)."""
        r = self.runner
        tree = self.tree()
        change_dir, groups = self.scope(state)
        return CheckLoop(
            check=lambda: r.run_stub_checks(cwd=tree),
            source=FeedbackSource.STUB_CHECKS,
            heading="",
            rounds="stub_rounds",
            commit=None,
            prompt=lambda feedback, note: STUB_CHECKS_PROMPT.format(
                commands=commands_note(r.repo_config),
                guidance=note,
                change_dir=change_dir,
                groups=groups,
                feedback=feedback,
            ),
            label="static checks on the tests",
            clears=lambda run: bool(run.stub_rounds),
            spent_message=lambda budget: (
                f"static checks still failing after {budget} fix round(s) on the tests"
            ),
            unchanged_message=lambda n: f"static checks failing and fix round {n} changed nothing",
        )

    def group_step(self, state: UnitRun) -> GroupStep | None:
        """The task group a stubbed build is on, None when the build is not stubbed."""
        steps = self.runner.group_steps(self.unit) if self.stubbed() else ()
        return steps[state.group] if state.group < len(steps) else None

    def scope(self, state: UnitRun) -> tuple[str, str]:
        """The change directory and group numbers a prompt names: the group a stubbed build
        is on, else the whole unit's."""
        step = self.group_step(state)
        if step is None:
            return self.runner.scope(self.unit)
        return step.change_dir, str(step.number)

    def title(self, state: UnitRun) -> str:
        """What a commit subject names: the group a stubbed build is on, else the unit."""
        step = self.group_step(state)
        return step.title if step else self.unit.title

    def message(self, prefix: str, tests: bool, state: UnitRun) -> str:
        """A commit message: the subject (the group's in a stubbed build, else the unit's), then a
        body saying why the change exists when it can: from the group being built, or from every
        group the unit builds when it is not stubbed."""
        step = self.group_step(state)
        steps = [step] if step else self.runner.group_steps(self.unit)
        body = commit_body(steps, tests=tests)
        return f"{prefix}{step.title if step else self.unit.title}" + (
            f"\n\n{body}" if body else ""
        )

    def unpaired(self, state: UnitRun, ref: str) -> str:
        """The stop for what the branch lacks for the group just built or an earlier one: a tests
        and implementation pair, a tests commit for a test-only group, or the tests commit a
        lone `feat:` has none before; "" when it lacks none."""
        steps = self.runner.group_steps(self.unit)
        progress = self.branch_progress(ref)
        if progress.done > state.group:
            return ""
        step = steps[progress.done]
        if step.test_only:
            return f"the branch holds no tests commit for group {step.number} ({step.title})"
        if progress.lone_feat:
            return (
                f"a feat: commit for group {step.number} has no test: commit before it "
                f"({progress.lone_feat})"
            )
        return (
            f"the branch holds no tests and implementation pair for group {step.number} "
            f"({step.title})"
        )

    def branch_progress(self, ref: str) -> GroupProgress:
        """How far the branch's commits get through the unit's groups, read from their subjects:
        the one reading resume, the pair count and the recorded-group decision share."""
        r = self.runner
        steps = r.group_steps(self.unit)
        return group_progress(
            r.branch_subjects(self.tree(), ref),
            [s.title for s in steps],
            [s.test_only for s in steps],
        )

    def half_recorded(self, state: UnitRun, progress: GroupProgress) -> bool:
        """Whether a killed run left this group's marked empty tests commit as the tip, with its
        implementation still to be recorded."""
        tree = self.tree()
        return (
            progress.done == state.group
            and progress.tests_made
            and recorded_built(tree, self.runner.head(tree))
        )

    def with_account(self, message: str, account: str) -> str:
        """A recorded group's commit message with the builder's account, redacted and cut,
        under its heading; the message as it is when the builder said nothing."""
        reason = redact_text(account, where="built group account")[:ACCOUNT_LIMIT].strip()
        return f"{message}\n\n{ACCOUNT_HEADING}\n{reason}" if reason else message

    def failed_unit_test(self, output: str) -> Update | None:
        """A failed unit-test run of this unit: the block when the environment is at fault,
        else the failure counted, said and saved as the feedback an agent is told of (None, and
        the caller picks its own stop)."""
        if (broken := self.environment_problem()) is not None:
            return self.blocked(broken)
        self.say(output)
        self.record_check_failure(output, 0)
        self.runner.store.set_feedback(
            self.unit.id, f"{UNIT_TEST_FAILED}\n{output}".strip(), source=FeedbackSource.UNIT_TEST
        )
        return None

    def record_built(self, state: UnitRun, ref: str, made: int, account: str) -> Update | None:
        """Record a group its agents left nothing to commit for, once the whole repository's unit
        tests pass: an empty marked `test:` and `feat:` (a test-only group's `test:` alone, which
        holds the account). None when nothing is to be recorded; a stop or a block when the
        tests do not pass."""
        r = self.runner
        step = self.group_step(state)
        tree = self.tree()
        if step is None or made or not r.branch_commits(tree, ref):
            return None
        progress = self.branch_progress(ref)
        if progress.done != state.group or progress.lone_feat:
            return None  # a lone feat: is named by the stop, not mended by an empty pair
        resumed = self.half_recorded(state, progress)
        if r.head(tree) != state.head and not resumed:
            return None
        if (broken := self.environment_problem()) is not None:
            return self.blocked(broken)
        try:
            ok, output = r.run_unit_test(cwd=tree, base=ref, whole_repo=True)
        except FlakeFound as found:
            ok, output = False, found.flakes[0].output
        if not ok:
            if (broken := self.failed_unit_test(output)) is not None:
                return broken
            return self.stop(self.unpaired(state, ref))
        self.say(f"group {step.number} is already built and the unit tests pass: recorded")
        tests = self.message(TESTS_PREFIX, True, state)
        if not (resumed or progress.tests_made):
            r.commit_built(self.with_account(tests, account) if step.test_only else tests, cwd=tree)
        if not step.test_only:
            code = self.message(CODE_PREFIX, False, state)
            if progress.tests_made and not resumed:
                code = f"{code}\n\n{TESTS_ALREADY_PASS}"
            r.commit_built(self.with_account(code, account), cwd=tree)
        return None

    def settle_group(self, state: UnitRun, ref: str, commits: int) -> Update:
        """The update for the group just built: a stop when the branch holds commits but no
        pair for it and every group before it, else the next group's turn, with the person's
        note cleared after the last. A branch with no commit of its own is not counted: the
        work is already built, and the unit tests decide."""
        r, unit = self.runner, self.unit
        if commits and (missing := self.unpaired(state, ref)):
            # After every group, so a later group's tests are never written over a gap.
            return self.stop(missing)
        more = state.group + 1 < len(r.group_steps(unit))
        kept: Update = {"group": state.group + 1, "more_groups": more}
        if not more:
            # Kept until the last group, so every group's prompts carry the note.
            note = r.store.get(unit.id).guidance
            r.store.set_guidance(unit.id, "")
            kept["guidance_asked"] = guidance_asked(state, note)
        return kept

    def stubbed(self) -> bool:
        """Whether this unit is built stubbed: the setting is on and its profile supports stubs."""
        config = self.runner.repo_config
        return config is not None and stubbed_build(active().builders, profiles.get(config.profile))

    def implement(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, ref = self.tree(), self.ref(state)
        kept: Update = {}
        if r.head(tree) != state.head and not (
            self.group_step(state) is not None
            and self.half_recorded(state, self.branch_progress(ref))
        ):
            self.say("the implementation commit is already on the branch")
        else:
            change_dir, groups = self.scope(state)
            build_boundary, _ = r.boundary_notes(unit, self.graph)
            self.say(f"implement ({models().implement})")
            guidance = r.store.get(unit.id).guidance
            prompt = IMPLEMENTATION_PROMPT.format(
                commands=commands_note(r.repo_config),
                guidance=person_guidance(guidance),
                groups=groups,
                change_dir=change_dir,
                boundary=build_boundary,
                changelog=changelog_note(tree, r.repo_config),
            )
            prompt = self.told(prompt, self.scope_note())
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            account = self.agent(
                r.run,
                prompt,
                cwd=tree,
                state=state,
                model=models().implement,
                follow_up=IMPLEMENTATION_CONTINUATION.format(
                    changelog=changelog_note(tree, r.repo_config)
                ),
            )
            self.apply_fixers()
            made = r.commit(self.message(CODE_PREFIX, False, state), cwd=tree, base=ref)
            if (stopped := self.record_built(state, ref, made, account)) is not None:
                return stopped
            if self.group_step(state) is None:
                r.store.set_guidance(unit.id, "")
                kept["guidance_asked"] = guidance_asked(state, guidance)
        # Counted on the branch, not taken from the commit step: an agent that
        # commits its own work leaves the pipeline nothing to commit.
        commits = r.branch_commits(tree, ref)
        if self.group_step(state) is not None:
            # A group's pair is done: the next group's tests come before the checks.
            kept = self.settle_group(state, ref, commits)
            if "stopped" in kept:
                return kept
        return {**kept, "head": r.head(tree), "produced_nothing": commits == 0}

    def checks(self, state: UnitRun) -> Update:
        """Unit-test on the committed branch, before a reviewer is asked."""
        r = self.runner
        tree = self.tree()
        self.say("checks before review")
        if (broken := self.environment_problem()) is not None:
            return {**self.blocked(broken), "checks_ok": False}
        fault = self.worktree_fault(state)
        if fault is not None and fault.environment:
            return {**self.blocked(fault.output), "checks_ok": False}
        if (stopped := self.product_files(state)) is not None:
            return {**stopped, "checks_ok": False}

        def run_checks() -> tuple[bool, str]:
            try:
                if fault is not None:
                    ok, output = False, fault.output
                else:
                    ok, output = r.run_unit_test(
                        cwd=tree, base=self.ref(state), whole_repo=False, **self.answering(state)
                    )
            except FlakeFound as found:
                if (parked := self.wait_for_fix(found)) is not None:
                    raise CheckParked({**parked, "checks_ok": False}) from found
                ok, output = False, found.flakes[0].output
            if not ok and (broken := self.environment_problem()) is not None:
                raise CheckParked({**self.blocked(broken), "checks_ok": False})
            self.say("checks passed" if ok else "checks failed")
            return ok, output

        result = check_loop.check_round(self, state, self.checks_loop(state, run_checks))
        head = r.head(tree)
        if result.get("ok"):
            return {"checks_ok": True, "head": head}
        if "checks_ok" in result:  # parked or blocked: the routine hands the update back as is
            return result
        return {**result, "checks_ok": False, "head": head}

    def checks_loop(
        self, state: UnitRun, check: Callable[[], tuple[bool, str]] | None = None
    ) -> CheckLoop:
        """The checks loop's parameters for the shared routine: the unit-test run, and the
        `fix:` commit of each round. A fix round passes no check: only a check round runs it."""
        r, unit = self.runner, self.unit
        tree = self.tree()
        change_dir, groups = r.scope(unit)
        build_boundary, _ = r.boundary_notes(unit, self.graph)
        outside: list[str] = []

        def outside_once() -> str:
            """The note on commits outside the unit, read from git once, on the first fix."""
            if not outside:
                outside.append(self.outside_note(state, tree))
            return outside[0]

        def fix_prompt(feedback: str, note: str) -> str:
            return self.told(
                CHECKS_PROMPT.format(
                    commands=commands_note(r.repo_config),
                    guidance=note,
                    change_dir=change_dir,
                    groups=groups,
                    feedback=feedback,
                    boundary=build_boundary,
                ),
                outside_once(),
            )

        def continuation(feedback: str, note: str) -> str:
            return self.told(
                CHECKS_CONTINUATION.format(guidance=note, feedback=feedback),
                outside_once(),
            )

        return CheckLoop(
            check=check or (lambda: (True, "")),
            source=FeedbackSource.UNIT_TEST,
            heading=UNIT_TEST_FAILED,
            rounds="fix_rounds",
            commit="fix: {title} (checks, round {n})",
            prompt=fix_prompt,
            follow_up=continuation,
            label="checks",
            # Fixed: left saved, a resume would redo a fix already on the branch.
            clears=lambda _: r.store.get(unit.id).feedback_source is FeedbackSource.UNIT_TEST,
            already_done=lambda: r.head(tree) != state.head,
            on_failure=self.record_check_failure,
            spent_message=lambda budget: (
                f"checks still failing after {budget} fix round(s), before review"
            ),
            unchanged_message=lambda n: (
                f"checks failing and fix round {n} changed nothing, before review"
            ),
        )

    def product_files(self, state: UnitRun) -> Update | None:
        """The stop for an `[e2e-test]` unit whose branch changes a file that is no test path,
        doc, changelog or `Support:` path of its groups (read from the plan, so the builder
        cannot allow itself one); the files are saved as feedback of their own. None for a
        unit of another tier or a diff of tests and support."""
        r, unit = self.runner, self.unit
        if unit.tier != TestTier.E2E_TEST:
            return None
        support = [path for step in r.group_steps(unit) for path in step.support]
        files, _ = r.branch_diff(self.tree(), self.ref(state))
        product = [path for path in files if is_product_path(path, r.repo_config, support)]
        if not product:
            return None
        named = ", ".join(product)
        r.store.set_feedback(
            unit.id, SCOPE_FEEDBACK.format(files=named), source=FeedbackSource.SCOPE
        )
        return self.stop(f"the e2e-test unit changes product code: {named}")

    def product_defect(self, account: str, stored: StoredUnit) -> Update | None:
        """What an `[e2e-test]` unit's rework does with a `product-defect` block in the builder's
        account: a refused block stops the unit, a valid one is filed and parks the unit on
        its fix, and no block (or a unit of the fix change itself) is an ordinary rework."""
        r, unit = self.runner, self.unit
        if unit.tier != TestTier.E2E_TEST or stored.feedback_source not in (
            FeedbackSource.E2E,
            FeedbackSource.SCOPE,
        ):
            return None
        support = [path for step in r.group_steps(unit) for path in step.support]
        read = read_product_defect(
            account,
            failure=stored.feedback,
            repo=unit.repo,
            repos=active().repos,
            support=support,
        )
        if read is None:
            return None
        if isinstance(read, DefectRefused):
            return self.stop(read.reason)
        fix = r.on_product_defect(unit, read)
        if fix is None:
            return None
        # No saved failure, so the end of the wait resumes the unit and does not rework it.
        r.store.set_feedback(unit.id, "")
        return self.park_for_fix(f"waiting for the fix of the product defect {read.test}: {fix}")

    def answering(self, state: UnitRun) -> dict[str, str]:
        """The failed check a fix has just answered, for the run to select its tests by;
        nothing for the first check, a unit that has not failed, or a rework."""
        stored = self.runner.store.get(self.unit.id)
        if state.fix_rounds and stored.feedback_source is FeedbackSource.UNIT_TEST:
            return {"failed_output": stored.feedback}
        return {}

    def wait_for_fix(self, found: FlakeFound) -> Update | None:
        """Unit-test failed only on tests that passed alone: the unit is not failed for them.
        It waits, gated, for the change that fixes them, and runs unit-test again once that
        has merged. None when there is nothing to wait on, because the unit builds that
        fix: the flake is then a unit-test failure the unit's agent is told of."""
        r, unit = self.runner, self.unit
        fixes = [r.on_flake(unit, flake) for flake in found.flakes]
        if not any(fixes):
            return None
        return self.park_for_fix(waiting_note([flake.test for flake in found.flakes]))

    def park_for_fix(self, note: str) -> Update:
        """Hold the unit, gated, until the change that fixes what failed has merged, and
        run the check that found it again then."""
        update = self.hold(PLANNED, note, note, cause=Cause.GATED)
        self.runner.store.set_gated_requeue(self.unit.id, RequeueReason.RESUME)
        return update

    def park_for_split(self, splits: list[str], sha: str, snapshot: str) -> Update:
        """Hold the unit, planned, until the held splits whose tests did not run are released.
        Nothing is published and nothing counts against it: those tests have not failed."""
        held = self.runner.e2e_holds().held
        waiting = ", ".join(
            f"{name} ({held[name].reason})" if name in held else name for name in splits
        )
        update = self.hold(
            PLANNED,
            f"e2e-test tests of {waiting} did not run: the split is held",
            f"waiting for e2e-test split {', '.join(splits)}",
            cause=Cause.SPLIT_HELD,
        )
        self.runner.store.set_parked(self.unit.id, splits, sha, snapshot)
        return update

    def fix_checks(self, state: UnitRun) -> Update:
        result = check_loop.fix_round(self, state, self.checks_loop(state))
        if "stopped" in result:
            return result
        return {**result, "head": self.runner.head(self.tree())}

    def review(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        _, review_boundary = r.boundary_notes(unit, self.graph)
        total = active().global_limits.max_review_rounds
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
            guidance=state.guidance_asked,
            pending_replies=state.pending_replies,
        )
        if outside := self.outside_note(state, tree):
            context = {**context, "context": self.told(context.get("context", ""), outside).strip()}
        raw = self.agent(
            r.run_review if first else r.run_rework_review, cwd=tree, state=state, **context
        )
        weighed = r.weigh_review(unit, raw, judged=judged, rounds=rounds)
        split = self.record_round(round_number if zero else round_number + 1, weighed, state)
        update: Update = {
            "review_round": round_number if zero else round_number + 1,
            "adopted": False,
            "head": judged,
            "review_rounds": weighed.rounds,
            # Kept past the push, which clears the rounds: the review tab shows it.
            "last_findings": weighed.findings,
        }
        if weighed.approved:
            if split:
                return self.hold_too_big(update, split)
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
                    f"needs a human: {cut_head(why, 300, 'char')}",
                    f"needs a human: {cut_head(why, 200, 'char')}",
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
            reasoning = cut_head(" ".join(verdict.reasoning.split()), 280, "char")
            return {
                **update,
                **self.hold(
                    HELD,
                    f"escalated — {label} ({verdict.escalate}): {reasoning}",
                    f"escalated ({verdict.escalate}): {cut_head(reasoning, 200, 'char')}",
                    cause=escalated,
                    held_by=HeldBy.REVIEW,
                ),
            }
        if split:
            return self.hold_too_big(update, split)
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

    def hold_too_big(self, update: Update, split: SplitRequest) -> Update:
        """Hold the unit as too big for its tier, with the request to split it. The round is not
        counted: the unit is neither failed nor sent back for rework."""
        r, unit = self.runner, self.unit
        r.store.set_split_request(
            unit.id,
            StoredSplitRequest(
                earned=split.earned.value,
                planned=split.planned.value if split.planned else None,
                lines=split.lines,
                ceiling=split.ceiling,
                drivers=split.drivers,
            ),
        )
        note = (
            f"too big for its tier: {split.lines} changed lines, over the {split.earned} "
            f"ceiling of {split.ceiling}"
        )
        kept = {k: v for k, v in update.items() if k != "review_round"}
        return {
            **kept,
            **self.hold(HELD, note, note, cause=Cause.TOO_BIG_FOR_TIER, held_by=HeldBy.SIZE),
        }

    def group_texts(self) -> tuple[GroupText, ...]:
        """The unit's groups with the text of their tasks, as the verdict matches a driver."""
        steps = self.runner.group_steps(self.unit)
        texts: dict[str, str] = {}
        for step in steps:
            tasks = Path(step.change_dir) / "tasks.md"
            if step.change_dir not in texts:
                texts[step.change_dir] = tasks.read_text() if tasks.exists() else ""
        return tuple(
            GroupText(
                number=step.number,
                text="".join(group_sections(texts[step.change_dir], [step.number])),
            )
            for step in steps
        )

    def record_round(self, number: int, weighed: Weighed, state: UnitRun) -> SplitRequest | None:
        """Record the verdict of a review round and return its request to split the unit, if it
        has one. A failure is logged and the unit goes on, as if the verdict said nothing."""
        if not active().review.enabled:
            return None
        r, unit = self.runner, self.unit
        try:
            kind = unit.tier
            tree, base = self.tree(), self.ref(state)
            paths, lines = r.branch_diff(tree, base)
            facts = VerdictFacts(
                kind=kind,
                planned_estimate=ReviewTier.parse(unit.review_tier),
                red_first=GateResult.PASSED,
                unit_test=GateResult.PASSED,
                e2e_state=e2e_state_of(state, r.store.get(unit.id).e2e_state),
                classification=ReviewTier.parse(weighed.verdict.classification),
                protected_paths=tuple(p for p in paths if is_protected(active(), unit.repo, p)),
                flags=tuple(step.flag for step in r.group_steps(unit) if step.flag),
                open_required_findings=weighed.open_required,
                final=weighed.approved,
                changed_lines=lines,
                drivers=weighed.verdict.drivers,
                groups=self.group_texts(),
                size_waived=r.store.get(unit.id).size_waived,
            )
            verdicts = r.store.path.with_name(VERDICTS)
            unit_class = class_of(active(), unit.repo, kind, paths)
            entry = record_verdict(
                verdicts,
                unit=unit.id,
                change=unit.change,
                round=number,
                unit_class=unit_class,
                history=recorded_history(
                    verdicts, unit_class, verdicts.with_name(audit_record.AUDITS)
                ),
                repo=unit.repo,
                facts=facts,
                drivers=weighed.verdict.drivers,
                paths=paths,
                lines=lines,
                policy=active().review.auto_land,
                ceilings=ceilings_in_effect(r.repo_config, active()),
                buffer=active().review.ceiling_buffer,
            )
            return entry.split
        except Exception as error:
            r.log(f"verdict for {unit.id} not recorded: {error}")
            return None

    def forget_e2e_result(self) -> None:
        """A new head the agent wrote has no e2e result yet: the one stored belongs to the head it
        ran on. Called wherever a rework or an adapt writes one."""
        self.runner.store.record_e2e_state(self.unit.id, None)

    def rework(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, ref = self.tree(), self.ref(state)
        change_dir, groups = r.scope(unit)
        build_boundary, _ = r.boundary_notes(unit, self.graph)
        stored = r.store.get(unit.id)
        guidance = stored.guidance
        feedback = redact_text(
            stored.feedback or (WHOLE_ASK if guidance else ""), where="rework prompt"
        )
        failed_check = stored.feedback_source in (
            FeedbackSource.UNIT_TEST,
            FeedbackSource.E2E,
            FeedbackSource.SCOPE,
        )
        in_loop = state.verdict is Verdict.CHANGES
        note = person_guidance(guidance)
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
                        commands=commands_note(r.repo_config),
                        guidance=note,
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
                        guidance=note,
                        feedback=feedback,
                        changelog=changelog_note(tree, r.repo_config),
                    ),
                    outside,
                ),
            )
            kept["review_rounds"] = with_response(state.review_rounds, response)
            r.commit(
                f"fix: {unit.title} (review round {state.review_round})",
                cwd=tree,
                base=self.ref(state),
            )
            r.store.set_guidance(unit.id, "")
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
                        commands=commands_note(r.repo_config),
                        guidance=note,
                        groups=groups,
                        change_dir=change_dir,
                        feedback=feedback,
                        boundary=build_boundary,
                        rerun=CHECKS_PROMPT.advice(feedback, stored.feedback_source),
                    )
                    if failed_check
                    else REWORK_PROMPT.format(
                        commands=commands_note(r.repo_config),
                        guidance=note,
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
                    CHECKS_CONTINUATION.format(
                        guidance=note,
                        feedback=feedback,
                        rerun=CHECKS_CONTINUATION.advice(feedback, stored.feedback_source),
                    )
                    if failed_check
                    else REWORK_CONTINUATION.format(
                        guidance=note,
                        feedback=feedback,
                        pr=stored.pr or "(not yet opened)",
                        changelog=changelog_note(tree, r.repo_config),
                    ),
                    outside,
                ),
            )
            if (defect := self.product_defect(answer, stored)) is not None:
                return defect
            committed = r.commit(f"fix: {unit.title}", cwd=tree, base=self.ref(state))
            r.store.set_guidance(unit.id, "")
            said = parse_answer(answer) if answer else None
            if answer and stored.pr and not failed_check:
                # Only an existing pull request has a reviewer waiting in its threads.
                if said and not committed and not said.replies:
                    # Nothing changed and nobody was answered, so the pull request has nothing
                    # to read: the account stays in the run log.
                    self.say(
                        f"rework changed nothing and answered no comment: {said.summary.strip()}"
                    )
                else:
                    kept["pending_replies"] = (*state.pending_replies, answer)
                if stored.feedback_from_person:
                    # The next review still judges the work against what the person asked.
                    kept["person_comments"] = f"{state.person_comments}\n\n{feedback}".strip()
        if guidance:
            # The next review judges the work against what the person asked, whichever
            # prompt the agent had it in, and pull request or not.
            kept["guidance_asked"] = guidance_asked(state, guidance)
        self.forget_e2e_result()
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

    def unit_test(self, state: UnitRun) -> Update:
        """For a unit that produced nothing, and for a branch moved cleanly onto a new base."""
        r, unit = self.runner, self.unit
        base = state.base or self.base
        self.say("unit-test")
        if (broken := self.environment_problem()) is not None:
            return self.blocked(broken)
        fault = self.worktree_fault(state)
        if fault is not None and fault.environment:
            return self.blocked(fault.output)
        try:
            if fault is not None:
                ok, output = False, fault.output
            else:
                # Only a clean move says what base it left, and so how its run is scoped.
                moved = {"moved_from": state.moved_from} if state.moved else {}
                ok, output = r.run_unit_test(
                    cwd=self.tree(),
                    base=self.ref(state),
                    whole_repo=state.produced_nothing,
                    **moved,
                )
        except FlakeFound as found:
            if found.scoped:
                # The move did not cause it: recorded, and the unit goes on without waiting.
                fixes = [r.on_flake(unit, flake, wait=False) for flake in found.flakes]
                # A unit of the flake's own fix change has no fix to lean on: the flake is
                # a unit-test failure its agent is told of.
                ok, output = (True, "") if all(fixes) else (False, found.flakes[0].output)
            elif (parked := self.wait_for_fix(found)) is not None:
                return parked
            else:
                ok, output = False, found.flakes[0].output
        self.say(f"unit-test {'passed' if ok else 'failed'}")
        if not ok:
            if (broken := self.failed_unit_test(output)) is not None:
                return broken
            if state.moved:
                return self.rebase(state, f"unit-test failed on {base}", base=base)
            return self.stop("unit-test failed")
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

    def e2e(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        base = state.base or self.base
        self.say("e2e-test again on the moved commit" if state.moved else "e2e-test")
        tree = self.tree()
        # A scheduled unit runs the one split its change is named for, and only a failing
        # test of that split holds it.
        own = scheduled_split(unit.change, unit.repo) if state.scheduled else None
        if r.e2e_runs_whole(cwd=tree, base=base) and (
            held := r.on_e2e_gate(unit, splits=r.e2e_splits() if own is None else (own,))
        ):
            return self.park_for_fix(
                f"waiting for the fix change {', '.join(held)} of a failing test on the base"
            )
        before = r.store.get(unit.id)
        # A unit parked on a split resumes with that split alone, on the commit it passed on.
        resumed = bool(before.parked_splits) and r.head(tree) == before.parked_sha
        parts: list[str] = []
        left_out: list[str] = []
        # The splits of a resume that ran and passed, kept if the unit parks again on others.
        passed: list[str] = []
        sha = ""
        for split in before.parked_splits if resumed else [None]:
            split = split or own
            only = {} if split is None else {"only": split}
            ok, part = r.run_e2e(cwd=tree, base=base, **only)
            parts.append(part)
            result = r.e2e_result()
            left_out += result.parked if result else []
            if ok and not (result and result.parked):
                passed.append(part)
            sha = result.sha if result else sha
            if not ok:
                break
        snapshot = "\n\n".join(parts)
        if ok and left_out:
            kept = "\n\n".join([before.parked_snapshot, *passed]).strip()
            return self.park_for_split(left_out, sha, kept if resumed else snapshot)
        if before.parked_splits:
            r.store.set_parked(unit.id)
            if ok and resumed:
                snapshot = f"{before.parked_snapshot}\n\n{snapshot}".strip()
        r.store.record_e2e_state(unit.id, E2eState.PASSED if ok else E2eState.FAILED)
        ran_none = ok and r.e2e_ran_no_tests()
        self.say("e2e-test ran no test" if ran_none else f"e2e-test {'passed' if ok else 'failed'}")
        if ok:
            # Said while the run's result is at hand: `satisfied` may be resumed by a new runner.
            note = r.e2e_passed_note() if state.scheduled else ""
            return {"snapshot": snapshot, "e2e_ran_none": ran_none, "scheduled_note": note}
        for line in snapshot.splitlines():
            if "**Full output:**" in line:
                self.say(line.strip("- ").replace("**", ""))
        # The tail goes to the run log too: the run log is where a failed run is read.
        for line in [line for line in snapshot.splitlines() if line.strip()][-E2E_LOG_TAIL:]:
            self.say(line)
        verdict = r.e2e_verdict()
        if verdict is not None and verdict.pre_existing:
            parked = self.wait_for_preexisting(verdict)
            if parked is not None:
                return parked
        snapshot = feedback_snapshot(snapshot, verdict)
        # Kept, as unit-test's is: a failure that leaves no trace has to be reproduced by hand.
        if state.moved:
            r.store.set_feedback(
                unit.id, f"e2e-test failed:\n{snapshot}".strip(), source=FeedbackSource.E2E
            )
            return self.rebase(state, f"e2e-test failed on {base}", base=base)
        stored = r.store.get(unit.id)
        # Words a person left stay theirs: e2e-test's output is added to them, not
        # the other way round.
        review = stored.feedback_source is FeedbackSource.REVIEW
        r.store.set_feedback(
            unit.id,
            f"{stored.feedback}\n\ne2e-test failed:\n{snapshot}".strip(),
            from_person=stored.feedback_from_person,
            source=FeedbackSource.REVIEW if review else FeedbackSource.E2E,
        )
        return self.stop("e2e-test failed")

    def wait_for_preexisting(self, verdict: E2eVerdict) -> Update | None:
        """Tests that fail on the base too are recorded and each gets its fix change. A unit
        with nothing else failing then waits, gated, for those fixes and runs e2e-test again
        once they have merged. None when it does not wait: it has a failure of its own to
        fix, or it builds the fix itself."""
        r, unit = self.runner, self.unit
        wait = not (verdict.own or verdict.broken)
        fixes = [
            r.on_preexisting(unit, verdict, failure, wait=wait) for failure in verdict.pre_existing
        ]
        if not wait or not any(fixes):
            return None
        # Only the tests that got a fix change: one the record refused (an unknown or blocked
        # runtime) is not waited for.
        return self.park_for_fix(
            preexisting_waiting_note(
                [f.test for f, fix in zip(verdict.pre_existing, fixes, strict=True) if fix]
            )
        )

    def satisfied(self, state: UnitRun) -> Update:
        """Nothing of this unit's own on the branch, and what is at the tip passes:
        the work its groups called for arrived another way. Judged on the branch
        and the checks, never on a step's report of itself."""
        r, unit = self.runner, self.unit
        why = state.scheduled_note or "already implemented; unit-test passed"
        self.say(why if state.scheduled_note else "nothing to add and unit-test passes — satisfied")
        r.store.set_state(unit.id, SATISFIED, note=why)
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
        note = "; ".join([why, *r.release_dependents(stored)])
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
        self._forget_spec()
        return {
            "status": RunStatus.SATISFIED,
            "detail": why,
            "review_rounds": (),
            "pending_replies": (),
            "person_comments": "",
            "guidance_asked": "",
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
        except (AgentRateLimited, AgentInterrupted, NetworkUnavailable, ServiceUnavailable):
            raise
        except Exception as error:  # noqa: BLE001
            return self.rebase(state, f"moving onto {base} needed resolution: {error}", base=base)
        if moved is not None:
            if moved.conflict or moved.resolved:
                return self.rebase(state, f"moving onto {base} needed resolution", base=base)
            self.say(f"moved onto {base} cleanly; unit-test again")
        return {
            "base": base,
            "moved": moved is not None,
            "moved_from": moved.old_base if moved is not None else "",
        }

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
        # Before the body is built from the stored unit, which says what became of the e2e step.
        if e2e_state_of(state, None) is E2eState.DEFERRED:
            r.store.record_e2e_state(unit.id, E2eState.DEFERRED)
        stored = r.store.get(unit.id)
        reviewed = active().review.enabled
        recorded = latest_verdict(r.store.path.with_name(VERDICTS), unit.id) if reviewed else None
        # A unit reaching a pull request has had its tests seen to fail first and its unit-test
        # pass: the same facts `record_round` hands the verdict.
        facts = VerdictFacts(
            kind=stored.tier,
            red_first=GateResult.PASSED,
            unit_test=GateResult.PASSED,
            e2e_state=stored.e2e_state,
        )
        # A re-run asks again: `open_pr` finds the branch's pull request and updates it.
        body = partial(
            build_pr_body,
            stored,
            graph=self.graph or [stored],
            base=base,
            e2e_snapshot=state.snapshot or None,
            open_points=stored.feedback if state.spent else None,
            follow_ups=r.follow_ups_for(unit) or None,
            linear=r.linear(tree, local_ref(base, repo=unit.repo)),
            limit=forges.description_limit(),
            changes_dir=changes_dir_under(Path(r.planning_repo), active().planning.specs_dir),
            facts=facts,
            rounds=state.review_round if reviewed else None,
            verdict=TierVerdict(
                tier=recorded.tier, evidence_tier=recorded.evidence_tier, reason=recorded.reason
            )
            if recorded
            else None,
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
        if active().review.enabled and active().review.brief:
            # The record is no input to anything: a failure is logged and never holds the body.
            try:
                mark_brief(r.store.path.with_name(VERDICTS), unit.id)
            except Exception as failed:  # noqa: BLE001
                self.say(f"could not mark the verdict record as carrying the brief: {failed}")
        if state.spent:
            outstanding = cut_head(" ".join(stored.feedback.split()), 300, "char")
            note = f"rounds spent with work outstanding: {outstanding}"
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
        if runs_e2e(state):
            r.post_status(sha, True)
        # What the host did not take stays owed, for the next pass to post.
        unposted = tuple(
            left
            for answer in state.pending_replies
            if (
                left := r.reply(
                    repo=unit.repo,
                    pr=pr,
                    answer_text=answer,
                    sha=sha,
                    branch=branch_name(unit),
                )
            )
        )
        if state.given_comments:
            r.record_given(unit.repo, pr, list(state.given_comments))
        if state.had_feedback:
            r.store.set_feedback(unit.id, "")
        r.store.set_state(unit.id, IN_REVIEW, pr=pr, note=NO_TEST_RAN if state.e2e_ran_none else "")
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
            "guidance_asked": "",
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
            EventKind.UPSTREAM_CHANGED,
        ):
            # A person has the unit: nothing automatic touches it again.
            return {"event": None}
        update: Update = {"event": event}
        if event.kind is EventKind.REWORK:
            held = r.store.get(unit.id)
            if event.feedback_source is FeedbackSource.CONFLICT and not held.has_own_rework_input(
                state.head
            ):
                # A moved-base run starts at the move, which may settle the conflict before
                # any rework agent is asked: the router takes it for a moved base.
                update["event"] = event.model_copy(update={"kind": EventKind.BASE_MOVED})
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
        elif event.kind is EventKind.UPSTREAM_CHANGED:
            # Parked, not sent back to work: the approval, branch and pull request stay, and
            # the thread keeps waiting here for the release to resume it. Only a unit still in
            # review: a person's hold, or a build, that got there first is left as it is.
            if r.store.get(unit.id).state != IN_REVIEW:
                self.say("not in review any more, nothing to park")
                return {"event": None}
            r.store.set_state(unit.id, PLANNED, note=event.reason, cause=Cause.UPSTREAM_WENT_BACK)
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
                limits = active().global_limits
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
            if event.guidance:
                r.store.set_guidance(unit.id, event.guidance)
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
                note=f"{event.kind.value}: {event.reason or 'no reason given'}"
                + guidance_excerpt(event.guidance),
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
                        "blocked_by_environment": False,
                    }
                )
            else:
                update.update(self.fresh_run())
            # The run takes the base the store names when the tick starts it: the one
            # `verify_base` last recorded is the old one, its branch may be gone, and
            # a requeue may follow a dependency gained since.
            update["base"] = ""
        else:
            update["detail"] = event.kind.value
            if event.kind in (EventKind.MERGED, EventKind.CLOSED):
                self._forget_spec()
        return update

    @staticmethod
    def fresh_run(*, had_feedback: bool = False) -> Update:
        """A thread taking up work again: what the last run ended on is not this run's."""
        return {
            "verdict": None,
            "stopped": "",
            "blocked_by_environment": False,
            "status": None,
            "detail": "",
            "review_round": 0,
            "fix_rounds": 0,
            "checks_ok": False,
            "produced_nothing": False,
            "moved": False,
            "moved_from": "",
            "head_approved": False,
            "pushed_head": False,
            "opened": False,
            "head": "",
            "seen_comments": None,
            "given_comments": (),
            "comments_pending": False,
            "had_feedback": had_feedback,
            "stub_rounds": 0,
            "stub_loop": False,
            "group": 0,
            "more_groups": False,
            "test_only_done": False,
            "tests_account": "",
            "held": "",
            "hold_state": "",
            "hold_note": "",
            "adopted": False,
        }

    def failed(self, state: UnitRun) -> Update:
        outcome = self.runner.fail(
            self.unit,
            state.stopped,
            cause=Cause.ENVIRONMENT if state.blocked_by_environment else Cause.FAILED,
        )
        return {"status": outcome.status, "detail": outcome.detail}


def guidance_asked(state: UnitRun, note: str) -> str:
    """The notes the next review is told, with `note` added to those already kept."""
    return f"{state.guidance_asked}\n\n{note}".strip()


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
    if node in (Node.STUB_CHECKS, Node.FIX_STUB_CHECKS):
        return state.stub_rounds + 1
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


def e2e_state_of(state: UnitRun, stored: E2eState | None) -> E2eState | None:
    """The e2e state a unit has or is about to have: `deferred` when this run skips the e2e node,
    otherwise the one stored. The one place the deferral is decided, for the record and the
    verdict alike."""
    return E2eState.DEFERRED if state.e2e and not runs_e2e(state) else stored


def runs_e2e(state: UnitRun) -> bool:
    """Whether the unit goes through the e2e node before merge: an e2e-test unit, unless its
    repo defers the tier to verify. A scheduled run is the suite itself and never defers."""
    return state.e2e and (state.scheduled or not state.e2e_deferred)


def after_prepare(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.scheduled:
        return Node.E2E
    if state.conflict:
        return Node.ADAPT
    if state.pushed_head and (
        not state.opened or (state.pending_replies and not state.had_feedback)
    ):
        # The work is approved and on the remote: only the pull request step is left.
        # Feedback saved after the pull request was opened is still to be reworked.
        return Node.OPEN_PR
    if state.stub_loop:
        # Stopped or killed in the check loop on the tests: back to the fix the saved
        # output asks for.
        return Node.FIX_STUB_CHECKS
    if state.resume:
        # A stubbed build continues at the first group without its pair, whatever note or
        # restack feedback waits: the groups carry it in their prompts.
        return Node.IMPLEMENT if state.resume == RESUME_IMPLEMENT else Node.TESTS
    if state.had_feedback:
        return Node.REWORK
    if not state.base_commits:
        return Node.TESTS
    if state.head_approved:
        # Review approved exactly this commit: nothing was written since.
        return Node.E2E if runs_e2e(state) else Node.VERIFY_BASE
    return Node.CHECKS


def after_tests(state: UnitRun) -> Node:
    return halted(state) or (Node.STUB_CHECKS if state.stub_loop else Node.IMPLEMENT)


def after_stub_checks(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.stub_loop:
        return Node.FIX_STUB_CHECKS
    # A test-only group has no implementation step: on to the next group or the checks.
    return after_last_group(state) if state.test_only_done else Node.IMPLEMENT


def after_fix_stub_checks(state: UnitRun) -> Node:
    return halted(state) or Node.STUB_CHECKS


def after_implement(state: UnitRun) -> Node:
    return halted(state) or after_last_group(state)


def after_last_group(state: UnitRun) -> Node:
    """Where a finished group leads: the next group's tests, else the checks."""
    if state.more_groups:
        return Node.TESTS
    return Node.UNIT_TEST if state.produced_nothing else Node.CHECKS


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
    return Node.E2E if runs_e2e(state) else Node.VERIFY_BASE


def after_rework(state: UnitRun) -> Node:
    return halted(state) or (Node.UNIT_TEST if state.produced_nothing else Node.CHECKS)


def after_unit_test(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    if state.produced_nothing:
        return Node.SATISFIED
    if state.moved:
        # verify_base already moved the unit onto the base: nothing left to check there.
        return Node.E2E if runs_e2e(state) else Node.NEW_COMMENTS
    return Node.VERIFY_BASE


def after_e2e(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    if state.scheduled:
        return Node.SATISFIED
    return Node.NEW_COMMENTS if state.moved else Node.VERIFY_BASE


def after_verify_base(state: UnitRun) -> Node:
    if stop := halted(state):
        return stop
    if state.restack:
        return Node.PREPARE
    return Node.UNIT_TEST if state.moved else Node.NEW_COMMENTS


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
    Node.FIX_STUB_CHECKS,
    Node.CHECKS,
    Node.TESTS,
    Node.IMPLEMENT,
    Node.E2E,
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
    Node.TESTS: (after_tests, (Node.HELD, Node.FAILED, Node.STUB_CHECKS, Node.IMPLEMENT)),
    Node.STUB_CHECKS: (
        after_stub_checks,
        (
            Node.HELD,
            Node.FAILED,
            Node.FIX_STUB_CHECKS,
            Node.IMPLEMENT,
            Node.UNIT_TEST,
            Node.CHECKS,
            Node.TESTS,
        ),
    ),
    Node.FIX_STUB_CHECKS: (after_fix_stub_checks, (Node.HELD, Node.FAILED, Node.STUB_CHECKS)),
    Node.IMPLEMENT: (
        after_implement,
        (Node.HELD, Node.FAILED, Node.UNIT_TEST, Node.CHECKS, Node.TESTS),
    ),
    Node.CHECKS: (after_checks, (Node.HELD, Node.FAILED, Node.REVIEW, Node.FIX_CHECKS)),
    Node.FIX_CHECKS: (after_fix_checks, (Node.HELD, Node.FAILED, Node.CHECKS)),
    Node.REVIEW: (
        after_review,
        (Node.HELD, Node.FAILED, Node.PUSH, Node.E2E, Node.VERIFY_BASE, Node.REWORK),
    ),
    Node.REWORK: (after_rework, (Node.HELD, Node.FAILED, Node.UNIT_TEST, Node.CHECKS)),
    Node.UNIT_TEST: (
        after_unit_test,
        (
            Node.HELD,
            Node.FAILED,
            Node.PREPARE,
            Node.SATISFIED,
            Node.E2E,
            Node.VERIFY_BASE,
            Node.NEW_COMMENTS,
        ),
    ),
    Node.E2E: (
        after_e2e,
        (
            Node.HELD,
            Node.FAILED,
            Node.PREPARE,
            Node.SATISFIED,
            Node.VERIFY_BASE,
            Node.NEW_COMMENTS,
        ),
    ),
    Node.VERIFY_BASE: (
        after_verify_base,
        (Node.HELD, Node.FAILED, Node.PREPARE, Node.UNIT_TEST, Node.NEW_COMMENTS),
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
