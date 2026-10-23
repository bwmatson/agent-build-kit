"""The `review` keys that name what may land, its audit and its demotion (spec: auto-land)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.review_config import workspace

CLASSES = {"docs": ["**/*.md"], "tests": ["tests/**"]}


def landing(review: dict[str, Any]) -> dict[str, Any]:
    """The section as loaded, with `classes` supplied so a listed class is a known one."""
    return workspace({"classes": CLASSES, **review}).review.model_dump()


def refusal(review: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as refused:
        workspace({"classes": CLASSES, **review})
    return str(refused.value)


def test_a_workspace_with_none_of_the_keys_loads_with_the_defaults() -> None:
    dumped = workspace().review.model_dump()

    assert dumped["auto_land"]["classes"] == []
    assert dumped["audit"] == {"sample_rate": 0.1}
    assert dumped["demotion"] == {"window": 30, "min_agreement": 0.9}


def test_each_key_loads_when_set() -> None:
    dumped = landing(
        {
            "auto_land": {"classes": ["tests", "docs"]},
            "audit": {"sample_rate": 0.25},
            "demotion": {"window": 10, "min_agreement": 0.5},
        }
    )

    assert dumped["auto_land"]["classes"] == ["tests", "docs"]
    assert dumped["audit"] == {"sample_rate": 0.25}
    assert dumped["demotion"] == {"window": 10, "min_agreement": 0.5}


def test_the_older_auto_land_keys_still_load_beside_the_class_list() -> None:
    dumped = landing({"auto_land": {"classes": ["docs"], "min_samples": 5}})

    assert dumped["auto_land"]["classes"] == ["docs"]
    assert dumped["auto_land"]["min_samples"] == 5


def test_an_empty_list_is_the_off_switch() -> None:
    assert landing({"auto_land": {"classes": ["docs"]}})["auto_land"]["classes"] == ["docs"]

    assert landing({"auto_land": {"classes": []}})["auto_land"]["classes"] == []


def test_a_class_that_review_classes_does_not_name_is_refused_naming_it() -> None:
    assert landing({"auto_land": {"classes": ["docs"]}})["auto_land"]["classes"] == ["docs"]

    assert "typo" in refusal({"auto_land": {"classes": ["docs", "typo"]}})


def test_a_listed_class_with_no_classes_defined_is_refused() -> None:
    assert landing({"auto_land": {"classes": ["docs"]}})["auto_land"]["classes"] == ["docs"]

    with pytest.raises(ValidationError, match="docs"):
        workspace({"auto_land": {"classes": ["docs"]}})


@pytest.mark.parametrize("rate", [2, -0.1])
def test_a_sample_rate_outside_zero_to_one_is_refused_naming_the_key_and_value(rate: float) -> None:
    assert landing({"audit": {"sample_rate": 0.5}})["audit"]["sample_rate"] == 0.5

    message = refusal({"audit": {"sample_rate": rate}})

    assert "sample_rate" in message
    assert str(rate) in message


def test_the_rates_at_the_ends_of_the_range_load() -> None:
    for rate in (0, 1):
        assert landing({"audit": {"sample_rate": rate}})["audit"]["sample_rate"] == rate
        agreement = landing({"demotion": {"min_agreement": rate}})["demotion"]["min_agreement"]
        assert agreement == rate


@pytest.mark.parametrize("agreement", [1.5, -0.1])
def test_an_agreement_outside_zero_to_one_is_refused_naming_the_key(agreement: float) -> None:
    assert landing({"demotion": {"min_agreement": 0.5}})["demotion"]["min_agreement"] == 0.5

    assert "min_agreement" in refusal({"demotion": {"min_agreement": agreement}})


@pytest.mark.parametrize("window", [0, -3])
def test_a_window_below_one_is_refused_naming_the_key(window: int) -> None:
    assert landing({"demotion": {"window": 1}})["demotion"]["window"] == 1

    assert "window" in refusal({"demotion": {"window": window}})


@pytest.mark.parametrize("section", ["auto_land", "audit", "demotion"])
def test_an_unknown_key_is_refused_naming_it(section: str) -> None:
    assert landing({"audit": {"sample_rate": 0.5}})["audit"]

    assert "bogus" in refusal({section: {"bogus": 1}})


def test_a_repo_block_still_accepts_only_protected_paths_and_ceilings() -> None:
    assert landing({"audit": {"sample_rate": 0.5}})["audit"]
    loaded = workspace(app={"protected_paths": ["src/billing/**"]})
    assert loaded.repos["app"].review.model_dump()["protected_paths"] == ["src/billing/**"]

    for key, value in (("auto_land", {"classes": ["docs"]}), ("audit", {}), ("demotion", {})):
        with pytest.raises(ValidationError, match=key):
            workspace(app={key: value})
