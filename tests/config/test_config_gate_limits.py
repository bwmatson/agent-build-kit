"""`gate.provider.limits` and the gate's cache settings (spec: split-gate-usage)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.config import WorkspaceConfig
from tests.split_gate_config import PROVIDER, gate_of, provider_of, refusal, with_gate


def provider_with(limits: dict[str, Any]) -> dict[str, Any]:
    return {"provider": {**PROVIDER, "limits": limits}}


def test_the_four_window_limits_load_with_their_defaults() -> None:
    limits = provider_of(with_gate({"provider": PROVIDER})).limits

    assert limits.usage_pause_pct == 70
    assert limits.usage_pause_ceiling_pct is None
    assert limits.usage_ceiling_pct == 70
    assert limits.usage_relief_fraction == 0.25
    assert limits.usage_resume_buffer_pct == 5


def test_set_limits_load_and_a_ceiling_below_the_pause_percent_is_refused() -> None:
    limits = provider_of(
        with_gate(provider_with({"usage_pause_pct": 60, "usage_pause_ceiling_pct": 90}))
    ).limits
    assert (limits.usage_pause_pct, limits.usage_ceiling_pct) == (60, 90)

    message = refusal(provider_with({"usage_pause_pct": 60, "usage_pause_ceiling_pct": 50}))
    assert "usage_pause_ceiling_pct" in message


@pytest.mark.parametrize(
    ("limits", "setting"),
    [
        ({"session": {"usage_pause_pct": 60}}, "session"),
        ({"weekly": {"usage_pause_pct": 60}}, "weekly"),
        ({"usage_unit_allowance_pct": 3}, "usage_unit_allowance_pct"),
        ({"usage_allowance_floor_pct": 1}, "usage_allowance_floor_pct"),
        ({"usage_climb_floor": 0.5}, "usage_climb_floor"),
        ({"usage_estimate_max_starts": 1}, "usage_estimate_max_starts"),
    ],
)
def test_a_subscription_only_setting_is_refused_naming_it_and_claude_code(
    limits: dict[str, Any], setting: str
) -> None:
    message = refusal(provider_with(limits))

    assert setting in message
    assert "claude_code" in message


@pytest.mark.parametrize("key", ["usage_cache_minutes", "usage_stale_retry_minutes"])
def test_a_gate_setting_under_limits_is_sent_to_the_gate(key: str) -> None:
    message = refusal(provider_with({key: 5}))

    assert key in message
    assert "gate" in message
    assert "claude_code" not in message


@pytest.mark.parametrize("key", ["command", "provider"])
def test_the_answer_keys_under_limits_are_unknown_not_redirected(key: str) -> None:
    message = refusal(provider_with({key: ["probe"]}))

    assert f"gate.provider.limits.{key}" in message
    assert "beside `provider`" not in message


def test_limits_beside_a_command_are_refused_saying_a_command_has_no_window() -> None:
    message = refusal({"command": ["probe"], "limits": {"usage_pause_pct": 60}})

    assert "no window" in message


@pytest.mark.parametrize("gate", [{"provider": PROVIDER}, {"command": ["probe"]}])
def test_the_cache_settings_load_with_defaults_for_either_kind(gate: dict[str, Any]) -> None:
    loaded = gate_of(with_gate(gate))
    assert (loaded.usage_cache_minutes, loaded.usage_stale_retry_minutes) == (15, 5)

    tuned = {**gate, "usage_cache_minutes": 5, "usage_stale_retry_minutes": 2}
    loaded = gate_of(with_gate(tuned))
    assert (loaded.usage_cache_minutes, loaded.usage_stale_retry_minutes) == (5, 2)


@pytest.mark.parametrize("setting", ["usage_cache_minutes", "usage_stale_retry_minutes"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_cache_setting_of_zero_or_less_is_refused(setting: str, value: int) -> None:
    assert f"gate.{setting}" in refusal({"command": ["probe"], setting: value})


def test_the_claude_code_limits_load_as_before_beside_a_gate() -> None:
    sections = {"session": {"usage_pause_pct": 60}, "weekly": {"usage_pause_pct": 50}}
    gate = {"provider": PROVIDER}
    loaded = WorkspaceConfig.model_validate(
        {
            "runtimes": {"claude_code": {"limits": sections}},
            "tests": {"e2e_splits": {"acp": {"marker": "runtime_acp", "gate": gate}}},
        }
    )

    limits = loaded.runtimes["claude_code"].usage_limits
    assert limits.session.usage_pause_pct == 60
    assert limits.weekly.usage_pause_pct == 50
    assert provider_of(loaded).name == "modal"
