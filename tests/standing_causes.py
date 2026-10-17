"""The two kinds of cause as the spec names them, for tests that run over each."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import Cause

__all__ = ["EVENT", "STANDING"]

STANDING = [
    Cause.SPLIT_HELD,
    Cause.GATED,
    Cause.UPSTREAM_WENT_BACK,
    Cause.BASE_CHANGED,
    Cause.RESTACK_DEFERRED,
    Cause.RESTACK_CONFLICT,
    Cause.RESTACK_HANDED_BACK,
    Cause.HOST_UNAVAILABLE,
    Cause.NETWORK_UNAVAILABLE,
    Cause.SERVICE_UNAVAILABLE,
    Cause.ENVIRONMENT,
    Cause.REWORK,
    Cause.USAGE,
    Cause.DIRTY_WORKTREE,
    Cause.ATTACHED,
    Cause.NEEDS_HUMAN,
    Cause.REVIEWER_HOLD,
    Cause.TOOLCHAIN,
    Cause.DEPTH,
    Cause.REVIEW_ESCALATED_CLASS,
    Cause.REVIEW_ESCALATED_DISAGREEMENT,
]
EVENT = [
    Cause.REQUEUED,
    Cause.RELEASED,
    Cause.ADOPTED,
    Cause.MERGED,
    Cause.AUTO_LANDED,
    Cause.CLOSED,
    Cause.FAILED,
]
