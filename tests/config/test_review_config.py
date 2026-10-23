"""The `review` section of abk.yaml and the `review` block of a repo (spec: review-policy)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.review_config import workspace


def refusal(review: dict[str, Any] | None = None, *, app: dict[str, Any] | None = None) -> str:
    """What loading refuses: each error's setting path and message, with the input it echoes."""
    with pytest.raises(ValidationError) as refused:
        workspace(review, app=app)
    return str(refused.value)


def test_a_workspace_with_no_review_section_loads_with_the_defaults() -> None:
    loaded = workspace()

    assert loaded.review.model_dump() == {
        "enabled": True,
        "protected_paths": [],
        "protected_defaults": True,
        "classes": {},
        "auto_land": {
            "min_samples": 20,
            "min_clean_rate": 0.95,
            "allow_deferred_e2e": False,
            "classes": [],
        },
        "audit": {"sample_rate": 0.1},
        "demotion": {"window": 30, "min_agreement": 0.9},
        "ceilings": {"auto": 5000, "light": 2000, "full": 750},
        "ceiling_buffer": 0.2,
        "split_rounds": 2,
        "brief": True,
    }
    assert loaded.repos["app"].review.model_dump() == {
        "protected_paths": [],
        "ceilings": {"auto": None, "light": None, "full": None},
    }


def test_each_key_loads_when_set() -> None:
    loaded = workspace(
        {
            "enabled": True,
            "protected_paths": ["deploy/**"],
            "protected_defaults": False,
            "classes": {"docs": ["**/*.md"], "tests": ["tests/**"]},
            "auto_land": {"min_samples": 5, "min_clean_rate": 0.5, "allow_deferred_e2e": False},
        },
        app={"protected_paths": ["src/billing/**"]},
    )

    dumped = loaded.review.model_dump()
    assert dumped == {
        "enabled": True,
        "protected_paths": ["deploy/**"],
        "protected_defaults": False,
        "classes": {"docs": ["**/*.md"], "tests": ["tests/**"]},
        "auto_land": {
            "min_samples": 5,
            "min_clean_rate": 0.5,
            "allow_deferred_e2e": False,
            "classes": [],
        },
        "audit": {"sample_rate": 0.1},
        "demotion": {"window": 30, "min_agreement": 0.9},
        "ceilings": {"auto": 5000, "light": 2000, "full": 750},
        "ceiling_buffer": 0.2,
        "split_rounds": 2,
        "brief": True,
    }
    assert list(dumped["classes"]) == ["docs", "tests"], "the order is kept"
    assert loaded.repos["app"].review.model_dump() == {
        "protected_paths": ["src/billing/**"],
        "ceilings": {"auto": None, "light": None, "full": None},
    }


@pytest.mark.parametrize("key", ["audits", "protected_path"])
def test_an_unknown_key_in_the_section_is_refused_naming_it(key: str) -> None:
    assert workspace({"enabled": True}).review.model_dump()["enabled"] is True

    assert key in refusal({key: 1})


def test_an_unknown_key_under_auto_land_is_refused_naming_it() -> None:
    assert workspace({"auto_land": {"min_samples": 3}}).review.model_dump()["auto_land"]

    assert "classe" in refusal({"auto_land": {"classe": ["docs"]}})


@pytest.mark.parametrize("key", ["enabled", "classes", "auto_land"])
def test_a_repo_block_holds_only_protected_paths_and_ceilings(key: str) -> None:
    loaded = workspace(app={"protected_paths": ["src/billing/**"]})
    assert loaded.repos["app"].review.model_dump()["protected_paths"] == ["src/billing/**"]

    assert key in refusal(app={key: True})


@pytest.mark.parametrize("rate", [1.5, -0.1])
def test_a_rate_outside_zero_to_one_is_refused_naming_the_key_and_the_value(rate: float) -> None:
    assert workspace({"auto_land": {"min_clean_rate": 0.5}}).review.model_dump()["auto_land"]

    message = refusal({"auto_land": {"min_clean_rate": rate}})

    assert "min_clean_rate" in message
    assert str(rate) in message


def test_the_rates_at_the_ends_of_the_range_load() -> None:
    for rate in (0, 1):
        loaded = workspace({"auto_land": {"min_clean_rate": rate}})

        assert loaded.review.model_dump()["auto_land"]["min_clean_rate"] == rate


@pytest.mark.parametrize("samples", [0, -3])
def test_a_sample_count_below_one_is_refused_naming_the_key(samples: int) -> None:
    assert workspace({"auto_land": {"min_samples": 1}}).review.model_dump()["auto_land"]

    assert "min_samples" in refusal({"auto_land": {"min_samples": samples}})


def test_a_value_of_the_wrong_type_is_refused_naming_the_key() -> None:
    assert workspace({"protected_paths": ["deploy/**"]}).review.model_dump()["protected_paths"]

    assert "protected_paths" in refusal({"protected_paths": "deploy/**"})
