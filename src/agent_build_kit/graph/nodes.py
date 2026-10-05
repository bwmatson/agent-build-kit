"""The build path's nodes: `wiring.build_runner`'s callables, one step each.

A node killed partway runs again from its start (docs/unit-graph.md,
Durability), so each one first looks at what the world already holds — the
branch's tip, the pushed commit, the pull request — and does nothing twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from functools import partial
from pathlib import Path
from typing import Any

from agent_build_kit.config import active, models
from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.graph.state import Node, UnitRun, Verdict
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import (
    CHECKS_PROMPT,
    IMPLEMENTATION_PROMPT,
    PREDECESSOR_NOTE,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_PROMPT,
    TESTS_PROMPT,
    TIER1_FAILED,
    RunStatus,
    UnitRunner,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, Unit, branch_name, local_ref
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited

Update = dict[str, Any]


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
        self._tree: Path | None = None
        self._node = ""

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
            Node.TIER1: self.tier1,
            Node.VERIFY_BASE: self.verify_base,
            Node.PUSH: self.push,
            Node.OPEN_PR: self.open_pr,
            Node.FAILED: self.failed,
        }
        return {node: self._wrapped(node, body) for node, body in bodies.items()}

    def _wrapped(self, node: Node, body: Callable[[UnitRun], Update]):
        async def run(state: UnitRun) -> Update:
            attributes = {"unit": self.unit.id, "change": self.unit.change, "step": node.value}
            span: AbstractContextManager[object] = (
                self.tracer.start_as_current_span(node.value, attributes=attributes)
                if self.tracer
                else nullcontext()
            )
            with span:
                self._node = node.value
                self.say("started")
                # Off the loop: the callables block on agents and git.
                return await asyncio.to_thread(body, state)

        return run

    def say(self, message: str) -> None:
        """A progress line, for the tick log and the unit's run log."""
        line = f"{self._node}: {message}"
        self.runner.log(line)
        if self.run_log:
            self.run_log.emit(line)

    def stop(self, reason: str) -> Update:
        self.say(f"stopping: {reason}")
        return {"stopped": reason}

    def not_yet(self, what: str) -> Update:
        """The classic engine's handling of `what` is a later group of the change."""
        return self.stop(f"{what} is not handled by the graph engine yet")

    def tree(self) -> Path:
        if self._tree is None:
            self._tree = self.runner.worktree(self.unit, local_ref(self.base))
        return self._tree

    def ref(self, state: UnitRun) -> str:
        return local_ref(state.base or self.base)

    def prepare(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        branch = branch_name(unit)
        feedback = r.store.get(unit.id).feedback
        r.store.set_state(unit.id, "running", branch=branch)
        tree, ref = self.tree(), self.ref(state)
        existing = r.branch_commits(tree, ref)
        self.say(
            f"on {self.base}, {existing} commit(s) already on the branch"
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
                why = f"restack onto {self.base} conflicted: {error}"
                waiting = r.store.get(unit.id).feedback
                r.store.set_feedback(unit.id, f"{waiting}\n\n{why}".strip())
                return self.stop(why)
            if restacked is not None:
                if restacked.conflict:
                    return self.not_yet("adapting a unit onto a base it conflicts with")
                if restacked.resolved:
                    files = ", ".join(restacked.resolved)
                    self.say(f"restacked onto {self.base}, resolving {files}")
                    r.store.set_predecessor_note(
                        unit.id,
                        PREDECESSOR_NOTE.format(
                            onto_unit=restacked.onto_unit,
                            how=f"moving onto it needed conflict resolution in {files}",
                            decisions="",
                        ),
                    )
                else:
                    self.say(f"restacked onto {self.base} cleanly")
                existing = r.branch_commits(tree, ref)
        head = r.head(tree)
        return {
            "base_commits": existing,
            "had_feedback": bool(feedback),
            "head": head,
            "head_approved": bool(existing) and head == r.store.get(unit.id).approved,
        }

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
                groups=groups, change_dir=change_dir, boundary=build_boundary
            )
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            r.run_claude(prompt, cwd=tree)
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
                groups=groups, change_dir=change_dir, boundary=build_boundary
            )
            if note := r.follow_ups_note(unit):
                prompt = f"{note}\n\n{prompt}"
            r.run_claude(prompt, cwd=tree)
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
            if r.store.get(unit.id).feedback.startswith(TIER1_FAILED):
                # Fixed: left saved, a resume would redo a fix already on the branch.
                r.store.set_feedback(unit.id, "")
            return {"checks_ok": True, "head": head}
        self.say(output)
        # Kept before anything can stop the run, so a retry addresses this output.
        r.store.set_feedback(unit.id, f"{TIER1_FAILED}\n{output}".strip())
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
            self.say(f"fix the failing checks ({models().rework}), round {attempt}")
            r.run_rework(
                CHECKS_PROMPT.format(
                    change_dir=change_dir,
                    groups=groups,
                    feedback=r.store.get(unit.id).feedback,
                    boundary=build_boundary,
                ),
                cwd=tree,
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
        reworking = state.had_feedback or bool(r.store.get(unit.id).predecessor_note)
        first = round_number == 0 and not reworking
        if first:
            # A fresh build starts a fresh loop; a reworking one carries the rounds it had.
            r.store.set_review_rounds(unit.id, ())
        judged = r.head(tree)
        model = models().review if first else models().rework_review
        self.say(f"review round {round_number + 1} ({model})")
        context = r.review_notes(
            unit, round_number=round_number, total=total, review_boundary=review_boundary
        )
        raw = (r.run_review if first else r.run_rework_review)(cwd=tree, **context)
        weighed = r.weigh_review(unit, raw, judged=judged)
        update: Update = {"review_round": round_number + 1, "head": judged}
        if weighed.approved:
            if unit.tier == "tier2":
                return {**update, **self.not_yet("tier 2 after approval")}
            return {**update, "verdict": Verdict.APPROVED, "approved": judged, "fix_rounds": 0}
        if weighed.verdict.needs_human or r.escalates(weighed.verdict, weighed.earlier_rounds):
            return {**update, **self.not_yet("holding a unit for a person")}
        if round_number == total - 1:
            return {**update, **self.not_yet("a unit whose review rounds are spent")}
        # Kept as feedback, so the rework addresses what this round asked for.
        r.store.set_feedback(unit.id, weighed.why)
        return {**update, "verdict": Verdict.CHANGES, "fix_rounds": 0}

    def rework(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree, ref = self.tree(), self.ref(state)
        change_dir, groups = r.scope(unit)
        build_boundary, _ = r.boundary_notes(unit, self.graph)
        stored = r.store.get(unit.id)
        feedback = stored.feedback
        failed_check = feedback.startswith(TIER1_FAILED)
        in_loop = state.verdict is Verdict.CHANGES
        if r.head(tree) != state.head:
            self.say("the rework commit is already on the branch")
        elif in_loop:
            self.say(f"address review round {state.review_round} ({models().rework})")
            response = r.run_rework(
                REVIEW_FEEDBACK_PROMPT.format(
                    change_dir=change_dir, groups=groups, feedback=feedback, boundary=build_boundary
                ),
                cwd=tree,
            )
            r.record_response(unit, response)
            r.commit(f"fix: {unit.title} (review round {state.review_round})", cwd=tree)
        else:
            # One run on the review model, not the tests-then-implementation
            # pair: both are already on the branch.
            self.say(f"rework from feedback ({models().rework})")
            answer = r.run_rework(
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
                ),
                cwd=tree,
            )
            r.commit(f"fix: {unit.title}", cwd=tree)
            if answer and stored.pr and not failed_check:
                # Only an existing pull request has a reviewer waiting in its threads.
                r.store.set_pending_replies(unit.id, (*stored.pending_replies, answer))
        return {
            "verdict": None,
            "fix_rounds": 0,
            "head": r.head(tree),
            "produced_nothing": r.branch_commits(tree, ref) == 0,
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
            r.store.set_feedback(unit.id, f"{TIER1_FAILED}\n{output}".strip())
            return self.stop(
                "tier 1 failed" if state.produced_nothing else f"tier 1 failed on {base}"
            )
        if state.moved and r.head(self.tree()) != r.store.get(unit.id).approved:
            return self.not_yet("a move that changed what review approved")
        if state.produced_nothing:
            return self.not_yet("a unit with nothing to add")
        return {}

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
                base=local_ref(base),
                unit=unit,
                resolve=False,
            )
        except (AgentRateLimited, AgentInterrupted):
            raise
        except Exception as error:  # noqa: BLE001
            return self.not_yet(f"a base that moved and needs resolution ({error})")
        if moved is not None:
            if moved.conflict or moved.resolved:
                return self.not_yet("a base that moved and needs resolution")
            self.say(f"moved onto {base} cleanly; tier 1 again")
        return {"base": base, "moved": moved is not None}

    def push(self, state: UnitRun) -> Update:
        r, unit = self.runner, self.unit
        tree = self.tree()
        # The rule, checked where it matters: only the commit review approved leaves.
        head, approved = r.head(tree), r.store.get(unit.id).approved
        if not approved or head != approved:
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
            return self.not_yet(f"a host branch that moved under the push ({error})")
        self.say(f"pushed {branch} at {sha[:9]}")
        # Only now, with the push confirmed: a follow-up recorded ahead of it
        # would describe work that never left the machine.
        deferred = r.store.get(unit.id).deferred
        if deferred:
            r.record_follow_ups(unit, deferred)
            r.store.set_deferred(unit.id, ())
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
            follow_ups=r.follow_ups_for(unit) or None,
            linear=r.linear(tree, local_ref(base)),
        )
        try:
            pr = r.open_pr(
                unit,
                body=body(stacks=False),
                stacked_body=body(stacks=True),
                base=base,
                cwd=tree,
            )
        except BaseMissing:
            return self.not_yet("a base gone before its pull request")
        # Cleared only now, after the work is pushed and the pull request
        # updated: left in place, the next tick would rework the unit again for
        # a comment it has already answered.
        sha = r.head(tree)
        # After the push, never before: a status for a commit the host has not
        # seen is rejected.
        if unit.tier == "tier2":
            r.post_status(sha, True)
        for answer in stored.pending_replies:
            r.reply(repo=unit.repo, pr=pr, answer_text=answer, sha=sha)
        if stored.pending_replies:
            r.store.set_pending_replies(unit.id, ())
        if state.had_feedback:
            r.store.set_feedback(unit.id, "")
        r.store.set_state(unit.id, IN_REVIEW, pr=pr, resume_from="")
        if r.store.get(unit.id).predecessor_note:
            r.store.set_predecessor_note(unit.id, "")
        if r.store.get(unit.id).review_rounds:
            r.store.set_review_rounds(unit.id, ())
        # Done means through the loop, verified and pushed.
        r.mark_tasks(unit, done=True)
        self.say(f"in review: PR #{pr}")
        return {"status": RunStatus.OPEN, "detail": f"opened #{pr}", "pr": pr}

    def failed(self, state: UnitRun) -> Update:
        outcome = self.runner.fail(self.unit, state.stopped)
        return {"status": outcome.status, "detail": outcome.detail}


def after_prepare(state: UnitRun) -> Node:
    if state.stopped:
        return Node.FAILED
    if state.had_feedback:
        return Node.REWORK
    if not state.base_commits:
        return Node.TESTS
    # Review approved exactly this commit: nothing was written since.
    return Node.VERIFY_BASE if state.head_approved else Node.CHECKS


def after_implement(state: UnitRun) -> Node:
    return Node.TIER1 if state.produced_nothing else Node.CHECKS


def after_checks(state: UnitRun) -> Node:
    if state.stopped:
        return Node.FAILED
    return Node.REVIEW if state.checks_ok else Node.FIX_CHECKS


def after_fix_checks(state: UnitRun) -> Node:
    return Node.FAILED if state.stopped else Node.CHECKS


def after_review(state: UnitRun) -> Node:
    if state.stopped:
        return Node.FAILED
    return Node.VERIFY_BASE if state.verdict is Verdict.APPROVED else Node.REWORK


def after_rework(state: UnitRun) -> Node:
    return Node.TIER1 if state.produced_nothing else Node.CHECKS


def after_tier1(state: UnitRun) -> Node:
    return Node.FAILED if state.stopped else Node.VERIFY_BASE


def after_verify_base(state: UnitRun) -> Node:
    if state.stopped:
        return Node.FAILED
    return Node.TIER1 if state.moved else Node.PUSH


def after_push(state: UnitRun) -> Node:
    return Node.FAILED if state.stopped else Node.OPEN_PR


# Each node's router and the nodes it may name, which compiling checks.
ROUTES: Mapping[Node, tuple[Callable[[UnitRun], Node], tuple[Node, ...]]] = {
    Node.PREPARE: (
        after_prepare,
        (Node.FAILED, Node.REWORK, Node.CHECKS, Node.TESTS, Node.VERIFY_BASE),
    ),
    Node.IMPLEMENT: (after_implement, (Node.TIER1, Node.CHECKS)),
    Node.CHECKS: (after_checks, (Node.FAILED, Node.REVIEW, Node.FIX_CHECKS)),
    Node.FIX_CHECKS: (after_fix_checks, (Node.FAILED, Node.CHECKS)),
    Node.REVIEW: (after_review, (Node.FAILED, Node.VERIFY_BASE, Node.REWORK)),
    Node.REWORK: (after_rework, (Node.TIER1, Node.CHECKS)),
    Node.TIER1: (after_tier1, (Node.FAILED, Node.VERIFY_BASE)),
    Node.VERIFY_BASE: (after_verify_base, (Node.FAILED, Node.TIER1, Node.PUSH)),
    Node.PUSH: (after_push, (Node.FAILED, Node.OPEN_PR)),
}
