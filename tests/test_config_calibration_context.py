"""The two limits that bound what the planner is shown about each calibrated kind."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig


def limits_config(**overrides: object):
    return WorkspaceConfig.model_validate({"limits": overrides}).limits


def test_examples_default_to_three_and_zero_is_valid_but_negative_or_fractional_is_not() -> None:
    assert limits_config().calibration_examples == 3
    assert limits_config(calibration_examples=0).calibration_examples == 0

    for bad in (-1, 1.5, "many"):
        with pytest.raises(ValidationError, match="calibration_examples"):
            limits_config(calibration_examples=bad)


def test_kinds_listed_default_to_five_and_must_be_at_least_one_and_whole() -> None:
    assert limits_config().calibration_kinds_listed == 5
    assert limits_config(calibration_kinds_listed=1).calibration_kinds_listed == 1

    for bad in (0, -2, 2.5):
        with pytest.raises(ValidationError, match="calibration_kinds_listed"):
            limits_config(calibration_kinds_listed=bad)
