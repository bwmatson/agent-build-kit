"""The settings that choose how a window's usage is estimated (`runtimes.claude_code.limits`):
the basis (`cost` or `units`), the intercept of the cost fit, and the fit's minimum and quantile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.config import ClaudeLimitsConfig

WINDOWS = ("session", "weekly")


def write(root: Path, name: str, limits: dict[str, Any], *, account: bool = False) -> None:
    """Write `root/name` with `limits` under the runtime, or under an account's own block."""
    if account:
        runtime: dict[str, Any] = {"accounts": {"main": {"limits": limits}}}
    else:
        runtime = {"limits": limits}
    document = {"version": 1, "runtimes": {"claude_code": runtime}}
    (root / name).write_text(yaml.safe_dump(document))


def loaded(root: Path) -> ClaudeLimitsConfig:
    return config.load(root / "abk.yaml").runtimes["claude_code"].usage_limits


def test_the_defaults() -> None:
    found = ClaudeLimitsConfig()

    assert found.session.usage_estimate_basis == "cost"
    assert found.weekly.usage_estimate_basis == "cost"
    assert found.session.usage_estimate_intercept is True
    assert found.weekly.usage_estimate_intercept is False
    assert found.usage_cost_min_pairs == 8
    assert found.usage_cost_quantile == 0.9


@pytest.mark.parametrize("window", WINDOWS)
def test_abk_yaml_sets_each_window_apart(tmp_path: Path, window: str) -> None:
    write(
        tmp_path,
        "abk.yaml",
        {
            window: {
                "usage_estimate_basis": "units",
                "usage_estimate_intercept": window == "weekly",
            },
            "usage_cost_min_pairs": 12,
            "usage_cost_quantile": 0.75,
        },
    )

    found = loaded(tmp_path)
    other = "weekly" if window == "session" else "session"

    assert getattr(found, window).usage_estimate_basis == "units"
    assert getattr(found, window).usage_estimate_intercept is (window == "weekly")
    assert getattr(found, other).usage_estimate_basis == "cost"
    assert found.usage_cost_min_pairs == 12
    assert found.usage_cost_quantile == 0.75


def test_abk_local_yaml_sets_them_over_the_committed_file(tmp_path: Path) -> None:
    write(tmp_path, "abk.yaml", {"session": {"usage_estimate_basis": "cost"}})
    write(
        tmp_path,
        "abk.local.yaml",
        {
            "session": {"usage_estimate_basis": "units", "usage_estimate_intercept": False},
            "weekly": {"usage_estimate_intercept": True},
            "usage_cost_min_pairs": 10,
        },
    )

    found = loaded(tmp_path)

    assert found.session.usage_estimate_basis == "units"
    assert found.session.usage_estimate_intercept is False
    assert found.weekly.usage_estimate_intercept is True
    assert found.weekly.usage_estimate_basis == "cost"
    assert found.usage_cost_min_pairs == 10


def test_an_accounts_own_limits_block_sets_them(tmp_path: Path) -> None:
    write(
        tmp_path,
        "abk.yaml",
        {
            "weekly": {"usage_estimate_basis": "units"},
            "usage_cost_min_pairs": 5,
            "usage_cost_quantile": 0.8,
        },
        account=True,
    )

    own = config.load(tmp_path / "abk.yaml").runtimes["claude_code"].accounts["main"].usage_limits

    assert own.weekly.usage_estimate_basis == "units"
    assert own.session.usage_estimate_basis == "cost"
    assert own.usage_cost_min_pairs == 5
    assert own.usage_cost_quantile == 0.8


@pytest.mark.parametrize(
    ("limits", "key"),
    [
        ({"session": {"usage_estimate_basis": "dollars"}}, "usage_estimate_basis"),
        ({"weekly": {"usage_estimate_basis": "dollars"}}, "usage_estimate_basis"),
        ({"usage_cost_min_pairs": 0}, "usage_cost_min_pairs"),
        ({"usage_cost_min_pairs": 31}, "usage_cost_min_pairs"),
        ({"usage_allowance_window": 10, "usage_cost_min_pairs": 11}, "usage_cost_min_pairs"),
        ({"usage_cost_quantile": 0}, "usage_cost_quantile"),
        ({"usage_cost_quantile": -0.5}, "usage_cost_quantile"),
        ({"usage_cost_quantile": 1.1}, "usage_cost_quantile"),
    ],
)
def test_a_bad_value_is_refused_naming_the_key(
    tmp_path: Path, limits: dict[str, Any], key: str
) -> None:
    write(
        tmp_path,
        "abk.yaml",
        {"usage_allowance_window": 10, "usage_cost_min_pairs": 10, "usage_cost_quantile": 1},
    )
    assert loaded(tmp_path).usage_cost_min_pairs == 10

    write(tmp_path, "abk.yaml", limits)

    with pytest.raises(config.ConfigError, match=key) as refused:
        loaded(tmp_path)

    assert "Extra inputs" not in str(refused.value)
