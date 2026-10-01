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
