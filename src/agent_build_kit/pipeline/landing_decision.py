"""The landing decision: whether a unit may be merged by the pipeline, from plain facts."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.units import IN_REVIEW
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


def _first_unmet(facts: LandingFacts) -> tuple[Condition, str] | None:
    """The first condition the facts do not meet, with the reason in words."""
    checks: list[tuple[bool, Condition, str]] = [
        (facts.review_enabled, Condition.REVIEW_DISABLED, "review is not enabled"),
        (facts.state == IN_REVIEW, Condition.NOT_IN_REVIEW, "the unit is not in review"),
        (not facts.feedback_pending, Condition.FEEDBACK_PENDING, "feedback is still pending"),
        (not facts.held, Condition.HELD, "the unit is held"),
        (facts.verdict_tier is not None, Condition.NO_VERDICT, "the unit has no recorded verdict"),
        (
            facts.verdict_tier is ReviewTier.AUTO,
            Condition.TIER_NOT_AUTO,
            f"the verdict is {facts.verdict_tier}, not auto",
        ),
        (
            facts.unit_class is not None and facts.unit_class in facts.listed_classes,
            Condition.CLASS_NOT_LISTED,
            f"the class {facts.unit_class or '(none)'} is not enabled for landing",
        ),
        (
            facts.unit_class not in facts.demoted_classes,
            Condition.CLASS_DEMOTED,
            f"the class {facts.unit_class} is demoted",
        ),
        (facts.forge_merges, Condition.FORGE_DOES_NOT_MERGE, "the forge does not merge"),
        (facts.pr_open, Condition.PULL_REQUEST_CLOSED, "the pull request is not open"),
        (not facts.draft, Condition.DRAFT, "the pull request is a draft"),
        (not facts.conflicting, Condition.CONFLICT, "the pull request has a conflict"),
        (HOLD_LABEL not in facts.labels, Condition.HOLD_LABEL, "the pull request is held by label"),
        (
            not facts.changes_requested,
            Condition.CHANGES_REQUESTED,
            "changes are requested on the pull request",
        ),
        (
            facts.approved_head is not None and facts.head == facts.approved_head,
            Condition.HEAD_MOVED,
            "the pull request head is not the commit review approved",
        ),
        (
            not facts.unmerged_parents,
            Condition.PARENT_UNMERGED,
            f"the unit waits for its parent {', '.join(facts.unmerged_parents)} to merge",
        ),
    ]
    return next(((c, why) for ok, c, why in checks if not ok), None)


def decide_landing(facts: LandingFacts) -> LandingDecision:
    unmet = _first_unmet(facts)
    if unmet is None:
        return LandingDecision(may_land=True)
    condition, reason = unmet
    return LandingDecision(may_land=False, condition=condition, reason=reason)
