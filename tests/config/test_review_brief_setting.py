"""`review.brief` (spec: review-brief, "A setting turns the brief off")."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig


def load(review: dict[str, Any] | None = None) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "repos": {
                "app": {"path": "/work/app", "slug": "example/app"},
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
            "review": review or {},
        }
    )


def refusal(review: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as refused:
        load(review)
    return str(refused.value)


def test_with_no_brief_the_setting_loads_as_true() -> None:
    assert load().review.model_dump()["brief"] is True


def test_false_loads_as_false() -> None:
    assert load({"brief": False}).review.model_dump()["brief"] is False


def test_a_value_that_is_not_a_boolean_fails_naming_the_key() -> None:
    message = refusal({"brief": "sometimes"})

    assert "brief" in message
    assert "valid boolean" in message


def test_an_unknown_key_beside_it_still_fails_naming_only_the_unknown_key() -> None:
    message = refusal({"brief": False, "bogus": 1})

    assert "bogus" in message
    assert "Extra inputs are not permitted" in message
    assert "brief" not in message
