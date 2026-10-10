"""The graph's node names and the state a unit's thread carries."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.stack_runner import Restacked, RunStatus
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason, ReworkKind


class Node(StrEnum):
    PREPARE = "prepare"
    TESTS = "tests"
    IMPLEMENT = "implement"
    CHECKS = "checks"
    FIX_CHECKS = "fix_checks"
    REVIEW = "review"
    REWORK = "rework"
    ADAPT = "adapt"
    TIER1 = "tier1"
    TIER2 = "tier2"
    VERIFY_BASE = "verify_base"
    NEW_COMMENTS = "new_comments"
    PUSH = "push"
    OPEN_PR = "open_pr"
    AWAIT_REVIEW = "await_review"
    HELD = "held"
    SATISFIED = "satisfied"
    FAILED = "failed"


class SessionRole(StrEnum):
    BUILD = "build"
    REVIEW = "review"


class AgentSession(Frozen):
    session_id: str
    runtime: str
    model: str
    node: Node
    round: int
    head: str
    cumulative_usd: float | None = None  # the session's running cost after its last call


class Verdict(StrEnum):
    APPROVED = "approved"
    CHANGES = "changes"
    ESCALATED = "escalated"


class EventKind(StrEnum):
    REWORK = "rework"
    BASE_MOVED = "base_moved"
    HOLD = "hold"
    RELEASE = "release"
    MERGED = "merged"
    CLOSED = "closed"
    REQUEUE = "requeue"
    ADOPTED = "adopted"
    UPSTREAM_CHANGED = "upstream_changed"


class ResumeEvent(Frozen):
    kind: EventKind
    reason: str = ""
    feedback: str = ""
    from_person: bool = False  # the feedback is words a person left on the pull request
    feedback_source: FeedbackSource = FeedbackSource.NONE
    requeue: RequeueReason | None = None
    rework: ReworkKind | None = None
    # The ids of every comment the dispatch built that feedback from (the poller's listing and
    # the notes it read), which is all the agent is given. None when the dispatch named none.
    comment_ids: tuple[str, ...] | None = None


class UnitRun(Frozen):
    unit_id: str
    change: str
    groups: tuple[int, ...] = ()
    # The review loop so far: each round's ask and the builder's response, for
    # later rounds to check against instead of starting over.
    review_rounds: tuple[dict[str, Any], ...] = ()
    # The findings of the latest review round, whatever it decided. Unlike `review_rounds`
    # the push leaves it, so the review tab can show it once the unit has a pull request.
    last_findings: tuple[dict[str, Any], ...] = ()
    # The approved verdict's deferrable points, waiting for the push that makes them true.
    deferred: tuple[str, ...] = ()
    # A PR rework's replies, and the person's comments they answer, waiting for the
    # push that makes them true.
    pending_replies: tuple[str, ...] = ()
    person_comments: str = ""
    # Ids of every comment a rework covers: those it was delivered with, and those it has
    # taken in since. None when no rework is checking comments, which an empty tuple (a
    # pull request nobody had commented on) is not.
    seen_comments: tuple[str, ...] | None = None
    # The ids of those the agent was actually given, which the poller must not report
    # again once the push is made: the delivered ones, and the words each pass took in.
    given_comments: tuple[str, ...] = ()
    comments_pending: bool = False  # `new_comments` found words for the rework to address
    commits: tuple[str, ...] = ()
    verdict: Verdict | None = None
    stopped: str = ""
    blocked_by_environment: bool = False  # the stop is the environment's, not the unit's
    event: ResumeEvent | None = None
    session_id: str = ""  # the agent session the running node reported, until the node completes
    running_node: str = ""  # the agent node whose run started, until that node completes
    parked_node: str = ""  # the node a dirty tree parked the unit at, which a requeue goes back to
    sessions: Mapping[SessionRole, AgentSession] = {}  # each role's latest session
    build_model: str = ""  # the model the build session started on
    # What the build path routes on and what a re-run checks against git.
    base: str = ""  # the base the unit is on, once `verify_base` found it moved
    base_commits: int = 0  # commits on the branch when `prepare` finished
    head: str = ""  # the branch's tip when the last node finished, which a re-run compares with
    head_approved: bool = False  # the branch has work and review approved exactly its tip
    pushed_head: bool = False  # the approved commit is the pushed head
    opened: bool = False  # the unit has a pull request
    had_feedback: bool = False  # feedback was waiting when the run began
    fix_rounds: int = 0  # fixes of failing checks in this round of review
    review_round: int = 0
    checks_ok: bool = False
    produced_nothing: bool = False
    moved: bool = False  # `verify_base` moved the branch onto a new base
    start: str = (
        ""  # the base's tip when `prepare` began, which a held unit checks the base against
    )
    tier2: bool = False  # the unit is a tier 2 unit
    conflict: Restacked | None = None  # a restack that could not be merged, for `adapt` to port
    spent: bool = False  # the review rounds ran out with points outstanding
    adopted: bool = False  # the next review follows a chat's commit and is round zero
    snapshot: str = ""  # tier 2's results, for the pull request body
    restack: bool = False  # go back to `prepare`: the base moved before the push
    rebased: bool = False  # the run already went back once, so the next time it holds
    # Why the run holds, and the state the store is left in.
    held: str = ""
    hold_state: str = ""
    hold_note: str = ""
    # How the run ended, as `RunOutcome` reports it.
    status: RunStatus | None = None
    detail: str = ""
    pr: int | None = None
