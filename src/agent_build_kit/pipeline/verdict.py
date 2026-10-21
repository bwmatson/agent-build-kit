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


def compute_verdict(facts: VerdictFacts) -> Verdict:
    """The highest floor the facts give, with the rule that decided it. Calls no model."""
    raise NotImplementedError
