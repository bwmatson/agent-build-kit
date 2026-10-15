"""`gate.command`, its timeout and `on_unknown` (spec: split-gate-usage)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.split_gate_config import gate_of, refusal, with_gate


def test_a_command_loads_as_an_argv_with_the_defaults() -> None:
    gate = gate_of(with_gate({"command": ["probe", "--quiet"]}))

    assert list(gate.command) == ["probe", "--quiet"]
    assert gate.timeout_seconds == 30
    assert str(gate.on_unknown) == "allow"


@pytest.mark.parametrize("command", [[], "probe --quiet"], ids=["empty", "string"])
def test_an_empty_argv_or_a_string_is_refused(command: Any) -> None:
    assert "gate.command" in refusal({"command": command})


def test_the_timeout_is_set_and_must_be_greater_than_zero() -> None:
    assert gate_of(with_gate({"command": ["p"], "timeout_seconds": 5})).timeout_seconds == 5

    for bad in (0, -1):
        assert "timeout_seconds" in refusal({"command": ["p"], "timeout_seconds": bad})


@pytest.mark.parametrize("value", ["allow", "hold"])
def test_on_unknown_accepts_allow_and_hold(value: str) -> None:
    assert str(gate_of(with_gate({"command": ["p"], "on_unknown": value})).on_unknown) == value


def test_any_other_on_unknown_is_refused_naming_the_setting_and_both_values() -> None:
    message = refusal({"command": ["p"], "on_unknown": "ignore"})

    assert "on_unknown" in message
    assert "allow" in message
    assert "hold" in message
