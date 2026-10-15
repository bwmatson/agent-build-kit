"""`tests.tier2_splits.<name>.gate.provider` (spec: split-gate-usage)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump
from tests.split_gate_config import PROVIDER, provider_of, refusal, with_gate


def test_a_provider_loads_and_config_show_prints_it(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    loaded = with_gate({"provider": PROVIDER})
    path = tmp_path / "abk.yaml"
    path.write_text(dump(loaded))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    provider = shown["tests"]["tier2_splits"]["acp"]["gate"]["provider"]
    assert provider["name"] == "modal"
    assert provider["budget_usd"] == 200
    assert provider_of(loaded).budget_usd == 200


def test_an_unknown_name_is_refused_naming_the_setting_and_the_table() -> None:
    message = refusal({"provider": {"name": "other", "budget_usd": 50}})

    assert "gate.provider.name" in message
    assert "modal" in message


@pytest.mark.parametrize(
    "budget", [None, 0, -5, float("inf")], ids=["missing", "zero", "negative", "infinite"]
)
def test_a_missing_zero_negative_or_infinite_budget_is_refused_naming_it(
    budget: float | None,
) -> None:
    provider: dict[str, Any] = {"name": "modal"}
    if budget is not None:
        provider["budget_usd"] = budget

    assert "budget_usd" in refusal({"provider": provider})


@pytest.mark.parametrize("key", ["command", "budget"])
def test_an_unknown_key_under_provider_is_refused_naming_it(key: str) -> None:
    assert f"gate.provider.{key}" in refusal({"provider": {**PROVIDER, key: 5}})


def test_a_gate_with_neither_provider_nor_command_is_refused_saying_one_is_needed() -> None:
    message = refusal({"on_unknown": "hold"})

    assert "provider" in message
    assert "command" in message


def test_a_gate_with_both_is_refused_naming_both() -> None:
    message = refusal({"provider": PROVIDER, "command": ["probe"]})

    assert "provider" in message
    assert "command" in message


def test_rest_may_carry_a_gate_alone_or_with_a_hold() -> None:
    alone = with_gate({"provider": PROVIDER}, split="rest")
    held = WorkspaceConfig.model_validate(
        {"tests": {"tier2_splits": {"rest": {"hold": True, "gate": {"provider": PROVIDER}}}}}
    )

    assert provider_of(alone, "rest").name == "modal"
    assert provider_of(held, "rest").name == "modal"


def test_an_empty_rest_is_refused_saying_hold_or_gate() -> None:
    with pytest.raises(ValidationError, match="hold` or `gate"):
        WorkspaceConfig.model_validate({"tests": {"tier2_splits": {"rest": {}}}})


def test_a_workspace_with_no_gate_loads_and_dumps_unchanged() -> None:
    plain = WorkspaceConfig.model_validate(
        {"tests": {"tier2_splits": {"acp": {"marker": "runtime_acp"}}}}
    )

    assert "gate" in dump(with_gate({"provider": PROVIDER}))
    assert "gate" not in dump(plain)
    assert yaml.safe_load(dump(plain))["tests"]["tier2_splits"] == {
        "acp": {"marker": "runtime_acp"}
    }
