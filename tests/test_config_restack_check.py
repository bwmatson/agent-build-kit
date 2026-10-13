"""`limits.restack_check` selects how much of tier 1 a clean move runs (spec:
a-moved-base-is-checked-by-what-it-can-affect): `affected` by default, or `full`."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig


def limits(**given: Any) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return LimitsConfig.model_validate(given)


def from_yaml(text: str) -> Any:
    return LimitsConfig.model_validate(yaml.safe_load(text))


def test_a_moved_base_is_checked_by_what_it_can_affect_by_default() -> None:
    assert limits().restack_check == "affected"


def test_the_full_suite_can_be_asked_for() -> None:
    assert limits(restack_check="full").restack_check == "full"


def test_the_default_value_is_accepted_when_written() -> None:
    assert from_yaml("restack_check: affected").restack_check == "affected"


@pytest.mark.parametrize("value", ["scoped", "Full", "", "none"])
def test_any_other_value_is_refused(value: str) -> None:
    with pytest.raises(ValidationError, match="restack_check") as refused:
        limits(restack_check=value)

    assert "Extra inputs" not in str(refused.value)


@pytest.mark.parametrize(
    "text", ["restack_check: true", "restack_check: false", "restack_check: off"]
)
def test_an_unquoted_boolean_is_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="restack_check") as refused:
        from_yaml(text)

    assert "Extra inputs" not in str(refused.value)
