"""The graph's node names and the state a unit's thread carries."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.stack_runner import EarlierAnswer, Finding, FollowUp


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
    PUSH = "push"
    OPEN_PR = "open_pr"
    AWAIT_REVIEW = "await_review"
    HELD = "held"
    SATISFIED = "satisfied"
    FAILED = "failed"


class Verdict(StrEnum):
    APPROVED = "approved"
    CHANGES = "changes"
    ESCALATED = "escalated"


class EventKind(StrEnum):
    REWORK = "rework"
    BASE_MOVED = "base_moved"
    HOLD = "hold"
    MERGED = "merged"
    CLOSED = "closed"
    REQUEUE = "requeue"


class ReviewRound(Frozen):
    findings: tuple[Finding, ...] = ()
    answers: tuple[EarlierAnswer, ...] = ()
    response: str = ""


class ResumeEvent(Frozen):
    kind: EventKind
    reason: str = ""
    feedback: str = ""


class UnitRun(Frozen):
    unit_id: str
    change: str
    groups: tuple[int, ...] = ()
    rounds: tuple[ReviewRound, ...] = ()
    approved: str = ""
    deferred: tuple[FollowUp, ...] = ()
    pending_replies: tuple[str, ...] = ()
    predecessor_note: str = ""
    commits: tuple[str, ...] = ()
    verdict: Verdict | None = None
    stopped: str = ""
    event: ResumeEvent | None = None
    # What the build path routes on and what a re-run checks against git.
    base: str = ""  # the base the unit is on, once `verify_base` found it moved
    base_commits: int = 0  # commits on the branch when `prepare` finished
    head: str = ""  # the branch's tip when the last node finished, which a re-run compares with
    had_feedback: bool = False  # feedback was waiting when the run began
    fix_rounds: int = 0  # fixes of failing checks in this round of review
    review_round: int = 0
    checks_ok: bool = False
    produced_nothing: bool = False
    moved: bool = False  # `verify_base` moved the branch onto a new base
    # How the run ended, as `RunOutcome` reports it.
    status: str = ""
    detail: str = ""
    pr: int | None = None
