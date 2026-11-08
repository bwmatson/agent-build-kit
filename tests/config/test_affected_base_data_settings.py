"""`checks.affected.base_data_kept` and `checks.affected.base_data_max_age_hours` (spec:
selection-data-comes-from-the-base): how many base recordings are kept and how old the last may
be before a moved base is recorded again."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import AffectedConfig


def affected(**given: Any) -> dict[str, Any]:
    return AffectedConfig.model_validate(given).model_dump()


def test_three_recordings_are_kept_by_default() -> None:
    assert affected()["base_data_kept"] == 3


def test_a_recording_may_be_twelve_hours_old_by_default() -> None:
    assert affected()["base_data_max_age_hours"] == 12


def test_both_settings_keep_a_value_above_zero() -> None:
    kept = affected(base_data_kept=1, base_data_max_age_hours=0.5)

    assert (kept["base_data_kept"], kept["base_data_max_age_hours"]) == (1, 0.5)


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize("name", ["base_data_kept", "base_data_max_age_hours"])
def test_a_value_that_is_not_above_zero_is_refused(name: str, value: int) -> None:
    assert affected(**{name: 1})[name] == 1  # the setting exists

    with pytest.raises(ValidationError, match=name):
        affected(**{name: value})
