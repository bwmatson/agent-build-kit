"""The deterministic verdict: how much review a unit needs, from facts already recorded."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import Frozen, TestTier


class ReviewTier(StrEnum):
    AUTO = "auto"
    LIGHT = "light"
    FULL = "full"


class GateResult(StrEnum):
    """What is recorded of a gate: a result that passed or failed, none yet, or one that runs
    after review and has not yet run (met in an interim verdict, missing in a final one)."""

    PASSED = "passed"
    FAILED = "failed"
    MISSING = "missing"
    PENDING = "pending"


class ClassHistory(Frozen):
    """The track record of a unit's class: units with a recorded outcome, and how many merged
    clean."""

    samples: int = 0
    clean: int = 0


class VerdictFacts(Frozen):
    """What is recorded about a unit: its estimate, the changed paths a protected glob matches,
    the flags of the groups it builds, its test kind, its gate results, the reviewer's open
    required findings and classification (none when missing), and whether the round is final."""

    kind: TestTier
    planned_estimate: ReviewTier | None = None
    protected_paths: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    red_first: GateResult = GateResult.MISSING
    unit_test: GateResult = GateResult.MISSING
    e2e_test: GateResult = GateResult.MISSING
    open_required_findings: int = 0
    classification: ReviewTier | None = None
    final: bool = False


class Verdict(Frozen):
    tier: ReviewTier
    evidence_tier: ReviewTier
    reason: str


NO_HISTORY = ClassHistory()
DEFAULT_POLICY = AutoLandConfig()
_ORDER = (ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL)
_FLOORED_FLAGS = ("contract", "narrow", "acceptance")


def compute_verdict(
    facts: VerdictFacts,
    history: ClassHistory = NO_HISTORY,
    policy: AutoLandConfig = DEFAULT_POLICY,
) -> Verdict:
    """The highest floor the facts give, with the rule that decided it. Calls no model.

    Floors are tried in the order the spec lists them; the first of the highest wins the reason.
    The evidence tier leaves out the floor the class's `history` gives under `policy`."""
    del history, policy
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
