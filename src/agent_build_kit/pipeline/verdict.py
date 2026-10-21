"""The deterministic verdict: how much review a unit needs, from facts already recorded."""

from __future__ import annotations

import re
from enum import StrEnum

from agent_build_kit.config import AutoLandConfig, CeilingsConfig, buffered
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.unit_store import E2eState


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


class GroupText(Frozen):
    """A task group of the unit: its number and the text of its tasks, which a driver naming a
    file is matched against."""

    number: int
    text: str = ""


class SplitRequest(Frozen):
    """Why a unit is held to be split: the tier it earned and was planned for, its changed lines,
    the buffered-from ceiling of the earned tier, and the group numbers that drove the tier."""

    earned: ReviewTier
    planned: ReviewTier | None = None
    lines: int
    ceiling: int
    drivers: tuple[int, ...] = ()


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
    # What the unit's stored e2e state says; none when nothing is recorded.
    e2e_state: E2eState | None = None
    open_required_findings: int = 0
    classification: ReviewTier | None = None
    final: bool = False
    # For the size step: the unit's changed lines, the reviewer's drivers (groups or files), the
    # unit's groups with their task text, and whether a person waived the unit's size.
    changed_lines: int | None = None
    drivers: tuple[str, ...] = ()
    groups: tuple[GroupText, ...] = ()
    size_waived: bool = False


class TierVerdict(Frozen):
    tier: ReviewTier
    evidence_tier: ReviewTier
    reason: str
    # Set when the unit is over its earned tier's buffered ceiling: hold it and split it.
    split: SplitRequest | None = None


NO_HISTORY = ClassHistory()
DEFAULT_POLICY = AutoLandConfig()
# The review tiers, least review first: the one order every comparison of tiers uses.
REVIEW_TIERS = tuple(ReviewTier)
_FLOORED_FLAGS = ("contract", "narrow", "acceptance")


def compute_verdict(
    facts: VerdictFacts,
    history: ClassHistory = NO_HISTORY,
    policy: AutoLandConfig = DEFAULT_POLICY,
    ceilings: CeilingsConfig | None = None,
    buffer: float = 0.0,
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
        gates.append(("e2e-test", _e2e_gate(facts.e2e_state)))
        if facts.e2e_state == E2eState.DEFERRED and not policy.allow_deferred_e2e:
            floors.append((ReviewTier.LIGHT, "the e2e-test result was deferred to verify"))
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
    split = _size_step(facts, evidence_tier, ceilings, buffer)
    return TierVerdict(tier=tier, evidence_tier=evidence_tier, reason=reason, split=split)


# A driver that starts with a group number, written plainly or as "group 3" or "task group 3";
# whatever follows the number is ignored.
_GROUP_DRIVER = re.compile(r"(?:task\s+)?(?:groups?\s+)?(\d+)\b", re.IGNORECASE)


def _size_step(
    facts: VerdictFacts, earned: ReviewTier, ceilings: CeilingsConfig | None, buffer: float
) -> SplitRequest | None:
    """A request to split the unit when its changed lines pass the buffered ceiling of the tier
    its evidence earned; none when the lines or ceilings are not known or a person waived it."""
    if ceilings is None or facts.changed_lines is None or facts.size_waived:
        return None
    ceiling = getattr(ceilings, earned.value)
    if facts.changed_lines <= buffered(ceiling, buffer):
        return None
    return SplitRequest(
        earned=earned,
        planned=facts.planned_estimate,
        lines=facts.changed_lines,
        ceiling=ceiling,
        drivers=_driver_groups(facts),
    )


def _driver_groups(facts: VerdictFacts) -> tuple[int, ...]:
    """The unit's groups the drivers name, by number or by a file the group's text names, once
    each in group order; a driver matching no group of the unit is dropped."""
    named: set[int] = set()
    for driver in facts.drivers:
        match = _GROUP_DRIVER.match(driver.strip())
        if match:
            named.add(int(match.group(1)))
        else:
            path = re.compile(r"(?<![^\s`])" + re.escape(driver.strip()) + r"(?![^\s`])")
            named.update(g.number for g in facts.groups if path.search(g.text))
    return tuple(sorted(g.number for g in facts.groups if g.number in named))


def _e2e_gate(state: E2eState | None) -> GateResult:
    """The gate result a stored e2e state stands for: none is a gate yet to run."""
    if state is None:
        return GateResult.PENDING
    return GateResult.FAILED if state == E2eState.FAILED else GateResult.PASSED


def _highest(
    floors: list[tuple[ReviewTier, str]], tier: ReviewTier, reason: str
) -> tuple[ReviewTier, str]:
    """The highest floor; the first of equals keeps the reason."""
    for floor, why in floors:
        if REVIEW_TIERS.index(floor) > REVIEW_TIERS.index(tier):
            tier, reason = floor, why
    return tier, reason
