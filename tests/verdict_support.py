"""Verdict facts the verdict tests share: a unit whose recorded evidence is all green."""

from __future__ import annotations

from typing import Any

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.verdict import GateResult, ReviewTier, VerdictFacts


def green_facts(**changes: Any) -> VerdictFacts:
    """Facts with every gate passed, no open finding and an `auto` classification, so no floor
    comes from the evidence; `changes` overrides any field."""
    base: dict[str, Any] = {
        "kind": TestTier.UNIT_TEST,
        "red_first": GateResult.PASSED,
        "unit_test": GateResult.PASSED,
        "e2e_test": GateResult.PASSED,
        "classification": ReviewTier.AUTO,
    }
    return VerdictFacts(**{**base, **changes})
