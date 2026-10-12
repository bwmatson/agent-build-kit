"""`runtimes.<name>.policy: unchecked` records that the person carried on without the
agent's policy check; the strict schema takes that value and no other."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.config import PolicyMarker, RuntimeConfig


def entry(**fields: object) -> RuntimeConfig:
    return RuntimeConfig.model_validate(fields)


def test_an_entry_without_the_key_loads_unchanged() -> None:
    assert entry(command=["some-agent", "acp"]).policy is None
    assert entry().policy is None


def test_unchecked_loads() -> None:
    assert entry(command=["some-agent", "acp"], policy="unchecked").policy == PolicyMarker.UNCHECKED


@pytest.mark.parametrize("value", ["checked", "", "Unchecked", True, 1])
def test_any_other_value_is_refused(value: object) -> None:
    with pytest.raises(ValidationError):
        entry(policy=value)
