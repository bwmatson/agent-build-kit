"""The landing decision: whether a unit may be merged by the pipeline, from plain facts."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.verdict import ReviewTier


class Condition(StrEnum):
    """The conditions a unit must meet to land, one per way of being declined."""

    REVIEW_DISABLED = "review_disabled"
    NOT_IN_REVIEW = "not_in_review"
    FEEDBACK_PENDING = "feedback_pending"
    HELD = "held"
    NO_VERDICT = "no_verdict"
    TIER_NOT_AUTO = "tier_not_auto"
    CLASS_NOT_LISTED = "class_not_listed"
    CLASS_DEMOTED = "class_demoted"
    FORGE_DOES_NOT_MERGE = "forge_does_not_merge"
    PULL_REQUEST_CLOSED = "pull_request_closed"
    DRAFT = "draft"
    CONFLICT = "conflict"
    HOLD_LABEL = "hold_label"
    CHANGES_REQUESTED = "changes_requested"
    HEAD_MOVED = "head_moved"
    PARENT_UNMERGED = "parent_unmerged"


class LandingFacts(Frozen):
    """What is known of a unit and its pull request when the pipeline considers landing it."""

    review_enabled: bool
    state: str
    feedback_pending: bool = False
    held: bool = False
    # The recorded final verdict's tier; none when no final verdict is recorded.
    verdict_tier: ReviewTier | None = None
    unit_class: str | None = None
    # The policy and the demotions as they stand now.
    listed_classes: tuple[str, ...] = ()
    demoted_classes: tuple[str, ...] = ()
    forge_merges: bool = True
    pr_open: bool = True
    draft: bool = False
    conflicting: bool = False
    labels: tuple[str, ...] = ()
    changes_requested: bool = False
    head: str = ""
    approved_head: str | None = None
    # The units beneath this one that have not merged.
    unmerged_parents: tuple[str, ...] = ()


class LandingDecision(Frozen):
    """Whether the unit may land; when it may not, the condition and the reason in words."""

    may_land: bool
    condition: Condition | None = None
    reason: str = ""


def decide_landing(facts: LandingFacts) -> LandingDecision:
    raise NotImplementedError
