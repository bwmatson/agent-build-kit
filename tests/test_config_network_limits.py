"""`global_limits.network_probe_timeout_seconds` and `global_limits.network_control_hosts`.

The probe that tells a network outage from a provider outage looks at each host for at
most the timeout, and at the control group: the forge hosts and the hosts named here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import LimitsConfig, RepoConfig, WorkspaceConfig, dump


def limits(**values: Any) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return LimitsConfig.model_validate(values)


def test_the_probe_timeout_is_five_seconds_by_default() -> None:
    assert limits().network_probe_timeout_seconds == 5


def test_a_positive_whole_number_of_seconds_is_taken() -> None:
    assert limits(network_probe_timeout_seconds=2).network_probe_timeout_seconds == 2


@pytest.mark.parametrize("value", [0, -1, 2.5])
def test_a_timeout_that_is_not_a_positive_whole_number_is_refused_by_name(value: float) -> None:
    assert limits(network_probe_timeout_seconds=1).network_probe_timeout_seconds == 1

    with pytest.raises(ValidationError, match="network_probe_timeout_seconds") as refused:
        limits(network_probe_timeout_seconds=value)

    assert "Extra inputs" not in str(refused.value)


def test_the_control_hosts_are_two_public_resolvers_by_default() -> None:
    assert list(limits().network_control_hosts) == ["one.one.one.one", "dns.google"]


def test_bare_host_names_are_taken_and_none_at_all_is_allowed() -> None:
    assert list(limits(network_control_hosts=["a.example.test"]).network_control_hosts) == [
        "a.example.test"
    ]
    assert list(limits(network_control_hosts=[]).network_control_hosts) == []


@pytest.mark.parametrize("entry", ["", "https://a.example.test", "a.example.test/path", " "])
def test_a_control_host_that_is_not_a_bare_name_is_refused_by_name(entry: str) -> None:
    assert list(limits(network_control_hosts=["ok.example.test"]).network_control_hosts)

    with pytest.raises(ValidationError, match="network_control_hosts") as refused:
        limits(network_control_hosts=[entry])

    assert "Extra inputs" not in str(refused.value)


def test_config_show_lists_both(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = WorkspaceConfig(repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")})
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)["global_limits"]
    assert shown["network_probe_timeout_seconds"] == 5
    assert shown["network_control_hosts"] == ["one.one.one.one", "dns.google"]
