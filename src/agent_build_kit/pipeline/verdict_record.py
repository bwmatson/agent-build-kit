"""The recorded verdict of each unit, one entry per unit in `runs/verdicts.json`."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.verdict import (
    DEFAULT_POLICY,
    NO_HISTORY,
    ClassHistory,
    ReviewTier,
    VerdictFacts,
)

# In the state directory beside the unit store.
VERDICTS = "verdicts.json"


class VerdictEntry(Frozen):
    """What is recorded of a unit's verdict after a review round."""

    unit: str
    change: str
    round: int
    final: bool
    unit_class: str
    planned_estimate: ReviewTier | None
    classification: ReviewTier | None
    drivers: tuple[str, ...]
    evidence_tier: ReviewTier
    tier: ReviewTier
    reason: str
    paths: tuple[str, ...]
    lines: int
    brief: bool


def record_verdict(
    path: Path,
    *,
    unit: str,
    change: str,
    round: int,
    unit_class: str,
    facts: VerdictFacts,
    drivers: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
    lines: int = 0,
    history: ClassHistory = NO_HISTORY,
    policy: AutoLandConfig = DEFAULT_POLICY,
) -> VerdictEntry:
    """Compute the verdict of `facts` and write it over the unit's entry in `path`, atomically.

    The entry is final when `facts.final`."""
    raise NotImplementedError
