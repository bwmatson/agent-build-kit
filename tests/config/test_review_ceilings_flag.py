"""The ceiling in effect for a tier follows `review.enabled` (spec: review-tier-ceilings)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.config import WorkspaceConfig, review_ceiling
from agent_build_kit.pipeline.verdict import ReviewTier


def load(
    *, enabled: bool, ceilings: dict[str, int] | None = None, **limits: int
) -> WorkspaceConfig:
    review: dict[str, Any] = {"enabled": enabled}
    if ceilings is not None:
        review["ceilings"] = ceilings
    return WorkspaceConfig.model_validate(
        {
            "repos": {"app": {"path": "/work/app", "slug": "example/app"}},
            "review": review,
            "global_limits": limits,
        }
    )


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(ReviewTier.AUTO, 5000), (ReviewTier.LIGHT, 2000), (ReviewTier.FULL, 750), (None, 750)],
)
def test_with_the_flag_on_each_tier_has_its_own_ceiling(
    tier: ReviewTier | None, expected: int
) -> None:
    config = load(enabled=True)

    assert review_ceiling(config.repos["app"], config, tier) == expected


@pytest.mark.parametrize("enabled", [True, False])
def test_max_unit_lines_alone_is_the_full_ceiling_under_both_flags(enabled: bool) -> None:
    config = load(enabled=enabled, max_unit_lines=600)

    assert review_ceiling(config.repos["app"], config, ReviewTier.FULL) == 600
