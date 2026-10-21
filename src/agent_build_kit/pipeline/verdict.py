"""The deterministic verdict: how much review a unit needs, from facts already recorded."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import Frozen, TestTier


class ReviewTier(StrEnum):
    AUTO = "auto"
    LIGHT = "light"
    FULL = "full"

    @classmethod
    def parse(cls, value: str | None) -> ReviewTier | None:
        """The tier a stored word names, or None for none or a word that is no tier."""
        return next((t for t in cls if t.value == value), None)


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


class TierVerdict(Frozen):
    tier: ReviewTier
    evidence_tier: ReviewTier
    reason: str


NO_HISTORY = ClassHistory()
DEFAULT_POLICY = AutoLandConfig()
# The review tiers, least review first: the one order every comparison of tiers uses.
REVIEW_TIERS = tuple(ReviewTier)
_FLOORED_FLAGS = ("contract", "narrow", "acceptance")


def compute_verdict(
    facts: VerdictFacts,
    history: ClassHistory = NO_HISTORY,
    policy: AutoLandConfig = DEFAULT_POLICY,
) -> TierVerdict:
    """The highest floor the facts give, with the rule that decided it. Calls no model.

    Floors are tried in the order the spec lists them; the first of the highest wins the reason.
    The evidence tier leaves out the floor the class's `history` gives under `policy`."""
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
    gates = [("red-first", facts.red_first), ("unit-test", facts.unit_test)]
    if facts.kind == TestTier.E2E_TEST:
        gates.append(("e2e-test", facts.e2e_test))
    for name, result in gates:
        if result == GateResult.FAILED:
            floors.append((ReviewTier.FULL, f"the {name} gate failed"))
        elif result == GateResult.MISSING or (result == GateResult.PENDING and facts.final):
            floors.append((ReviewTier.FULL, f"the {name} gate has no result"))
    if facts.open_required_findings:
        floors.append((ReviewTier.FULL, "the reviewer has an open required finding"))
    if facts.classification is None:
        floors.append((ReviewTier.FULL, "the reviewer gave no classification"))
    else:
        floors.append((facts.classification, f"the reviewer classified it {facts.classification}"))
    evidence_tier, reason = _highest(
        floors, ReviewTier.AUTO, "no recorded fact gives a floor above auto"
    )

    if history.samples < policy.min_samples:
        history_floor = (
            ReviewTier.LIGHT,
            f"its class has {history.samples} samples, fewer than the {policy.min_samples} needed",
        )
    elif history.clean / history.samples < policy.min_clean_rate:
        history_floor = (
            ReviewTier.LIGHT,
            f"its class merges clean {history.clean / history.samples:.0%} of the time, "
            f"below the {policy.min_clean_rate:.0%} needed",
        )
    else:
        history_floor = None
    tier, reason = _highest(
        [(evidence_tier, reason), *([history_floor] if history_floor else [])],
        ReviewTier.AUTO,
        reason,
    )
    return TierVerdict(tier=tier, evidence_tier=evidence_tier, reason=reason)


def _highest(
    floors: list[tuple[ReviewTier, str]], tier: ReviewTier, reason: str
) -> tuple[ReviewTier, str]:
    """The highest floor; the first of equals keeps the reason."""
    for floor, why in floors:
        if REVIEW_TIERS.index(floor) > REVIEW_TIERS.index(tier):
            tier, reason = floor, why
    return tier, reason
