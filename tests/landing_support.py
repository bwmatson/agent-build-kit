"""Landing facts the landing tests share: a unit that meets every condition."""

from __future__ import annotations

from typing import Any

from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline.landing_decision import LandingFacts
from agent_build_kit.pipeline.verdict import ReviewTier

HEAD = "a" * 40


def check(name: str, status: CheckStatus = CheckStatus.PASSED) -> Check:
    return Check(name=name, status=status)


def facts(**changes: Any) -> LandingFacts:
    """A unit that meets every condition; `changes` overrides any fact."""
    base: dict[str, Any] = {
        "review_enabled": True,
        "state": "in_review",
        "verdict_tier": ReviewTier.AUTO,
        "unit_class": "docs",
        "listed_classes": ("docs",),
        "head": HEAD,
        "approved_head": HEAD,
        "checks": (check("build"), check("lint"), check("test")),
    }
    return LandingFacts(**{**base, **changes})
