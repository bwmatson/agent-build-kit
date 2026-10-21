"""The `review.ceilings` setting: defaults, keys, order and floor (spec: review-tier-ceilings)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig


def load(ceilings: dict[str, Any] | None = None, **limits: int) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "repos": {"app": {"path": "/work/app", "slug": "example/app"}},
            "review": {} if ceilings is None else {"ceilings": ceilings},
            "global_limits": limits,
        }
    )


def refusal(ceilings: dict[str, Any], **limits: int) -> str:
    with pytest.raises(ValidationError) as refused:
        load(ceilings, **limits)
    return str(refused.value)


def test_a_workspace_with_no_ceilings_loads_with_the_defaults() -> None:
    assert load().review.model_dump()["ceilings"] == {"auto": 5000, "light": 2000, "full": 750}


def test_each_key_loads_when_set() -> None:
    loaded = load({"auto": 8000, "light": 3000, "full": 1000})

    assert loaded.review.model_dump()["ceilings"] == {"auto": 8000, "light": 3000, "full": 1000}


def test_an_unknown_tier_is_refused_naming_it() -> None:
    assert load({"auto": 5000}).review.model_dump()["ceilings"]["auto"] == 5000

    assert "medium" in refusal({"medium": 1500})


def test_light_above_auto_is_refused_naming_both_tiers_and_values() -> None:
    message = refusal({"auto": 1500, "light": 1800})

    assert all(word in message for word in ("auto", "light", "1500", "1800"))


def test_full_above_light_is_refused_naming_both_tiers_and_values() -> None:
    message = refusal({"light": 900, "full": 1200})

    assert all(word in message for word in ("light", "full", "900", "1200"))


def test_full_at_or_below_the_floor_is_refused_naming_the_floor_and_both_values() -> None:
    message = refusal({"full": 400}, min_unit_lines=400)

    assert all(word in message for word in ("full", "min_unit_lines", "400"))
