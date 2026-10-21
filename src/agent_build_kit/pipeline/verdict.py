"""The deterministic verdict: how much review a unit needs, from facts already recorded."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.model import Frozen, TestTier


class ReviewTier(StrEnum):
    AUTO = "auto"
    LIGHT = "light"
    FULL = "full"


class VerdictFacts(Frozen):
    """What the plan recorded about a unit: its estimate, the changed paths a protected glob
    matches, the flags of the groups it builds, and its test kind."""

    kind: TestTier
    planned_estimate: ReviewTier | None = None
    protected_paths: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


class Verdict(Frozen):
    tier: ReviewTier
    evidence_tier: ReviewTier
    reason: str


_ORDER = (ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL)
_FLOORED_FLAGS = ("contract", "narrow", "acceptance")


def compute_verdict(facts: VerdictFacts) -> Verdict:
    """The highest floor the facts give, with the rule that decided it. Calls no model.

    Floors are tried in the order the spec lists them; the first of the highest wins the reason."""
    floors: list[tuple[ReviewTier, str]] = []
    if facts.planned_estimate is not None:
        floors.append((facts.planned_estimate, f"the planned estimate is {facts.planned_estimate}"))
    if facts.protected_paths:
        floors.append(
            (ReviewTier.FULL, f"it changed the protected path {facts.protected_paths[0]}")
        )
    for flag in facts.flags:
        if flag in _FLOORED_FLAGS:
            floors.append((ReviewTier.FULL, f"a group it builds is flagged [{flag}]"))
            break
    tier, reason = ReviewTier.AUTO, "the plan gives no floor above auto"
    for floor, why in floors:
        if _ORDER.index(floor) > _ORDER.index(tier):
            tier, reason = floor, why
    return Verdict(tier=tier, evidence_tier=tier, reason=reason)
