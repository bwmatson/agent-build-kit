"""The settings that calibrate a window's usage allowance (`runtimes.claude_code.limits`).

`usage_unit_allowance_pct` takes a whole number or `auto`, a number being the cap on the
calibrated figure and the fallback; `auto` is the default."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ClaudeLimitsConfig


def limits(**values: Any) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return ClaudeLimitsConfig.model_validate(values)


def test_each_window_defaults_to_auto() -> None:
    assert limits().session.usage_unit_allowance_pct == "auto"
    assert limits().weekly.usage_unit_allowance_pct == "auto"


def test_auto_and_a_whole_number_are_taken() -> None:
    taken = limits(
        session={"usage_unit_allowance_pct": "auto"}, weekly={"usage_unit_allowance_pct": 3}
    )

    assert taken.session.usage_unit_allowance_pct == "auto"
    assert taken.weekly.usage_unit_allowance_pct == 3


@pytest.mark.parametrize("value", ["fast", 2.5, -1])
def test_an_allowance_that_is_neither_a_whole_number_nor_auto_is_refused_by_name(
    value: object,
) -> None:
    assert limits(weekly={"usage_unit_allowance_pct": "auto"})

    with pytest.raises(ValidationError, match="usage_unit_allowance_pct"):
        limits(weekly={"usage_unit_allowance_pct": value})


def test_the_calibration_settings_have_their_defaults() -> None:
    found = limits()

    assert found.weekly.usage_unit_allowance_pct == "auto"
    assert found.calibrate_usage_allowances is True
    assert found.usage_allowance_quantile == 0.9
    assert found.usage_allowance_window == 30
    assert found.usage_allowance_min_pairs == 8
    assert found.session.usage_allowance_floor_pct == 1
    assert found.weekly.usage_allowance_floor_pct == 1


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("usage_allowance_quantile", 0),
        ("usage_allowance_quantile", 1.1),
        ("usage_allowance_window", 0),
        ("usage_allowance_min_pairs", 0),
    ],
)
def test_a_bad_value_is_refused_naming_the_key(key: str, value: float) -> None:
    with pytest.raises(ValidationError, match=key):
        limits(**{key: value})


def test_a_minimum_above_the_window_is_refused_naming_the_key() -> None:
    with pytest.raises(ValidationError, match="usage_allowance_min_pairs"):
        limits(usage_allowance_window=5, usage_allowance_min_pairs=6)


def test_a_floor_above_the_cap_is_refused_naming_the_key() -> None:
    assert limits(weekly={"usage_unit_allowance_pct": 3, "usage_allowance_floor_pct": 3})

    with pytest.raises(ValidationError, match="usage_allowance_floor_pct"):
        limits(weekly={"usage_unit_allowance_pct": 3, "usage_allowance_floor_pct": 4})
