"""`review.ceiling_buffer` and `review.split_rounds` (spec: hold-and-split)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig


def load(
    review: dict[str, Any] | None = None, repo_review: dict[str, Any] | None = None
) -> WorkspaceConfig:
    app: dict[str, Any] = {"path": "/work/app", "slug": "example/app"}
    if repo_review is not None:
        app["review"] = repo_review
    return WorkspaceConfig.model_validate(
        {
            "repos": {
                "app": app,
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
            "review": review or {},
        }
    )


def refusal(review: dict[str, Any], repo_review: dict[str, Any] | None = None) -> str:
    with pytest.raises(ValidationError) as refused:
        load(review, repo_review)
    return str(refused.value)


def test_with_no_settings_the_buffer_is_a_fifth_and_the_rounds_are_two() -> None:
    dumped = load().review.model_dump()

    assert dumped["ceiling_buffer"] == 0.2
    assert dumped["split_rounds"] == 2


def test_each_setting_loads_when_set_in_range() -> None:
    dumped = load({"ceiling_buffer": 0.5, "split_rounds": 0}).review.model_dump()

    assert dumped["ceiling_buffer"] == 0.5
    assert dumped["split_rounds"] == 0


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_a_buffer_out_of_range_is_refused_naming_the_key_and_value(value: float) -> None:
    message = refusal({"ceiling_buffer": value})

    assert "ceiling_buffer" in message
    assert str(value) in message


@pytest.mark.parametrize("value", [3, -1])
def test_rounds_out_of_range_are_refused_naming_the_key_and_value(value: int) -> None:
    message = refusal({"split_rounds": value})

    assert "split_rounds" in message
    assert str(value) in message


def test_a_buffered_auto_ceiling_at_the_reading_limit_is_refused_naming_it_all() -> None:
    message = refusal({"ceilings": {"auto": 9000}})

    assert "9000" in message
    assert "0.2" in message
    assert "10000" in message or "10,000" in message


def test_a_buffered_auto_ceiling_under_the_limit_loads() -> None:
    dumped = load({"ceilings": {"auto": 8000}}).review.model_dump()

    assert dumped["ceiling_buffer"] == 0.2


def test_a_larger_ceiling_loads_when_the_buffer_is_zero() -> None:
    dumped = load({"ceilings": {"auto": 9900}, "ceiling_buffer": 0}).review.model_dump()

    assert dumped["ceilings"]["auto"] == 9900
    assert dumped["ceiling_buffer"] == 0


def test_the_same_check_applies_to_a_repos_merged_ceilings_naming_the_repo() -> None:
    message = refusal({}, {"ceilings": {"auto": 9000}})

    assert "app" in message
    assert "9000" in message
    assert "10000" in message or "10,000" in message
