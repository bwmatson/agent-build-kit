"""`tier2_schedule` is `daily`, `weekly`, `monthly` or `off`: a default under `limits` and an
optional override on a repo's `tests` block, the repo's winning (spec: tier2-schedule)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import (
    LimitsConfig,
    RepoConfig,
    Tier2Schedule,
    WorkspaceConfig,
    dump,
    tier2_schedule,
)

VALUES = ["daily", "weekly", "monthly", "off"]


def limits(**given: Any) -> Any:
    return LimitsConfig.model_validate(given)


def repo(**tests: Any) -> Any:
    return RepoConfig.model_validate({"path": "/work/app", "slug": "example/app", "tests": tests})


def test_the_default_is_weekly() -> None:
    assert limits().tier2_schedule == "weekly"
    assert tier2_schedule(repo(), limits()) is Tier2Schedule.WEEKLY


@pytest.mark.parametrize("value", VALUES)
def test_each_value_is_accepted_in_limits_and_on_a_repo(value: str) -> None:
    assert limits(tier2_schedule=value).tier2_schedule == value
    assert repo(tier2_schedule=value).tests.tier2_schedule == value


def test_a_repo_has_no_value_of_its_own_by_default() -> None:
    assert repo().tests.tier2_schedule is None


def test_an_unquoted_off_read_as_false_means_off() -> None:
    config = yaml.safe_load(
        "global_limits:\n  tier2_schedule: off\ntests:\n  tier2_schedule: off\n"
    )
    assert config["global_limits"]["tier2_schedule"] is False

    assert limits(**config["global_limits"]).tier2_schedule == "off"
    assert repo(**config["tests"]).tests.tier2_schedule == "off"
    assert tier2_schedule(repo(tier2_schedule=False), limits()) is Tier2Schedule.OFF


def test_true_is_not_a_schedule() -> None:
    with pytest.raises(ValidationError, match="tier2_schedule") as refused:
        limits(tier2_schedule=True)

    assert "Extra inputs" not in str(refused.value)


def test_the_repos_value_wins_over_limits() -> None:
    assert tier2_schedule(repo(tier2_schedule="off"), limits(tier2_schedule="daily")) == "off"
    assert tier2_schedule(repo(tier2_schedule="daily"), limits(tier2_schedule="off")) == "daily"


def test_a_repo_without_a_value_follows_limits() -> None:
    assert tier2_schedule(repo(), limits(tier2_schedule="monthly")) is Tier2Schedule.MONTHLY


@pytest.mark.parametrize("value", ["hourly", "Weekly", "", "none", "yearly"])
def test_any_other_value_in_limits_is_refused_naming_the_setting_and_the_four(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="tier2_schedule") as refused:
        limits(tier2_schedule=value)

    assert "Extra inputs" not in str(refused.value)
    assert all(name in str(refused.value) for name in VALUES)


@pytest.mark.parametrize("value", ["hourly", "Weekly", "", "none", "yearly"])
def test_any_other_value_on_a_repo_is_refused_naming_the_setting_and_the_four(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="tier2_schedule") as refused:
        repo(tier2_schedule=value)

    assert "Extra inputs" not in str(refused.value)
    assert all(name in str(refused.value) for name in VALUES)


def test_config_show_prints_the_values_set(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = WorkspaceConfig.model_validate(
        {
            "global_limits": {"tier2_schedule": "monthly"},
            "repos": {
                "app": {
                    "path": str(tmp_path / "app"),
                    "slug": "example/app",
                    "tests": {"tier2_schedule": "daily"},
                }
            },
        }
    )
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["global_limits"]["tier2_schedule"] == "monthly"
    assert shown["repos"]["app"]["tests"]["tier2_schedule"] == "daily"


def test_config_show_prints_the_default_when_nothing_is_set(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(
        dump(
            WorkspaceConfig.model_validate(
                {"repos": {"app": {"path": str(tmp_path / "app"), "slug": "example/app"}}}
            )
        )
    )

    assert main(["--config", str(path), "config", "--show"]) == 0

    assert yaml.safe_load(capsys.readouterr().out)["global_limits"]["tier2_schedule"] == "weekly"
