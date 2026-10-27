"""The settings of the start forecast (`runtimes.claude_code.limits`): whether it is made, the
units a tier needs before its history is used and the quantile its chances are bounded at."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.config import ClaudeLimitsConfig, ConfigError


def loaded(root: Path, limits: dict[str, Any]) -> ClaudeLimitsConfig:
    document = {"version": 1, "runtimes": {"claude_code": {"usage_limits": limits}}}
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    return config.load(root / "abk.yaml").runtimes["claude_code"].usage_limits


def test_the_defaults() -> None:
    found = ClaudeLimitsConfig()

    assert found.usage_forecast is True
    assert found.usage_forecast_min_runs == 10
    assert found.usage_forecast_quantile == 0.9


def test_abk_yaml_sets_them_beside_the_other_usage_settings(tmp_path: Path) -> None:
    found = loaded(
        tmp_path,
        {
            "usage_forecast": False,
            "usage_forecast_quantile": 0.75,
            "usage_headroom_margin_pct": 7,
        },
    )

    assert found.usage_forecast is False
    assert found.usage_forecast_min_runs == 10
    assert found.usage_forecast_quantile == 0.75
    assert found.usage_headroom_margin_pct == 7


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("usage_forecast_quantile", 0),
        ("usage_forecast_quantile", 1.1),
        ("usage_forecast_min_runs", 0),
    ],
)
def test_a_value_out_of_range_is_refused_naming_the_key(
    tmp_path: Path, key: str, value: float
) -> None:
    with pytest.raises(ConfigError, match=key):
        loaded(tmp_path, {key: value})


def test_a_quantile_of_one_is_allowed(tmp_path: Path) -> None:
    assert loaded(tmp_path, {"usage_forecast_quantile": 1}).usage_forecast_quantile == 1


def test_an_unknown_key_is_still_refused(tmp_path: Path) -> None:
    assert loaded(tmp_path, {}).usage_forecast_quantile == 0.9
    with pytest.raises(ConfigError, match="usage_forecast_quantil"):
        loaded(tmp_path, {"usage_forecast": True, "usage_forecast_quantil": 0.9})
