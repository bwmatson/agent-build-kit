"""A repo's `review.ceilings` override and what is in effect for it (spec: review-tier-ceilings)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig, review_ceiling
from agent_build_kit.pipeline.verdict import ReviewTier


def load(
    repo_ceilings: dict[str, Any],
    ceilings: dict[str, Any] | None = None,
    **limits: int,
) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "repos": {
                "app": {
                    "path": "/work/app",
                    "slug": "example/app",
                    "review": {"ceilings": repo_ceilings},
                },
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
            "review": {"enabled": True, "ceilings": ceilings or {}},
            "global_limits": limits,
        }
    )


def in_effect(config: WorkspaceConfig, repo: str) -> dict[str, int]:
    return {
        tier.value: review_ceiling(config.repos[repo], config, tier)
        for tier in (ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL)
    }


def refusal(
    repo_ceilings: dict[str, Any], ceilings: dict[str, Any] | None = None, **limits: int
) -> str:
    with pytest.raises(ValidationError) as refused:
        load(repo_ceilings, ceilings, **limits)
    return str(refused.value)


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("auto", {"auto": 3000, "light": 2000, "full": 750}),
        ("light", {"auto": 5000, "light": 1500, "full": 750}),
        ("full", {"auto": 5000, "light": 2000, "full": 900}),
    ],
)
def test_a_repo_override_of_one_tier_leaves_the_others_the_workspaces(
    tier: str, expected: dict[str, int]
) -> None:
    config = load({tier: expected[tier]})

    assert in_effect(config, "app") == expected


def test_a_repo_without_an_override_has_the_workspaces_ceilings() -> None:
    config = load({"auto": 3000}, {"auto": 6000, "light": 2500, "full": 900})

    assert in_effect(config, "app") == {"auto": 3000, "light": 2500, "full": 900}
    assert in_effect(config, "platform") == {"auto": 6000, "light": 2500, "full": 900}


def test_an_override_is_not_blamed_for_a_relation_between_inherited_values() -> None:
    config = load({"auto": 6000}, max_unit_lines=3000)

    assert review_ceiling(config.repos["app"], config, ReviewTier.FULL) == 3000
    assert review_ceiling(config.repos["app"], config, ReviewTier.AUTO) == 6000


def test_an_override_out_of_order_with_the_workspaces_tiers_is_refused_naming_the_repo() -> None:
    message = refusal({"auto": 1500}, {"light": 2000})

    assert all(word in message for word in ("app", "auto", "light", "1500", "2000"))


def test_an_override_of_light_below_the_workspaces_full_is_refused_naming_the_repo() -> None:
    message = refusal({"light": 600}, {"full": 750})

    assert all(word in message for word in ("app", "light", "full", "600", "750"))


def test_an_override_of_full_at_or_below_the_floor_is_refused_naming_the_repo() -> None:
    message = refusal({"full": 400}, min_unit_lines=400)

    assert all(word in message for word in ("app", "full", "min_unit_lines", "400"))
