"""`e2e_schedule` is `daily`, `weekly`, `monthly` or `off`: a default under `limits` and an
optional override on a repo's `tests` block, the repo's winning (spec: e2e-schedule)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import (
    E2eSchedule,
    LimitsConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
    e2e_schedule,
)

VALUES = ["daily", "weekly", "monthly", "off"]


def limits(**given: Any) -> Any:
    return LimitsConfig.model_validate(given)


def repo(**tests: Any) -> Any:
    return RepoConfig.model_validate({"path": "/work/app", "slug": "example/app", "tests": tests})


def test_the_default_is_weekly() -> None:
    assert limits().e2e_schedule == "weekly"
    assert e2e_schedule(repo(), limits()) is E2eSchedule.WEEKLY


@pytest.mark.parametrize("value", VALUES)
def test_each_value_is_accepted_in_limits_and_on_a_repo(value: str) -> None:
    assert limits(e2e_schedule=value).e2e_schedule == value
    assert repo(e2e_schedule=value).tests.e2e_schedule == value


def test_a_repo_has_no_value_of_its_own_by_default() -> None:
    assert repo().tests.e2e_schedule is None


def test_an_unquoted_off_read_as_false_means_off() -> None:
    config = yaml.safe_load("global_limits:\n  e2e_schedule: off\ntests:\n  e2e_schedule: off\n")
    assert config["global_limits"]["e2e_schedule"] is False

    assert limits(**config["global_limits"]).e2e_schedule == "off"
    assert repo(**config["tests"]).tests.e2e_schedule == "off"
    assert e2e_schedule(repo(e2e_schedule=False), limits()) is E2eSchedule.OFF


def test_true_is_not_a_schedule() -> None:
    with pytest.raises(ValidationError, match="e2e_schedule") as refused:
        limits(e2e_schedule=True)

    assert "Extra inputs" not in str(refused.value)


def test_the_repos_value_wins_over_limits() -> None:
    assert e2e_schedule(repo(e2e_schedule="off"), limits(e2e_schedule="daily")) == "off"
    assert e2e_schedule(repo(e2e_schedule="daily"), limits(e2e_schedule="off")) == "daily"


def test_a_repo_without_a_value_follows_limits() -> None:
    assert e2e_schedule(repo(), limits(e2e_schedule="monthly")) is E2eSchedule.MONTHLY


@pytest.mark.parametrize("value", ["hourly", "Weekly", "", "none", "yearly"])
def test_any_other_value_in_limits_is_refused_naming_the_setting_and_the_four(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="e2e_schedule") as refused:
        limits(e2e_schedule=value)

    assert "Extra inputs" not in str(refused.value)
    assert all(name in str(refused.value) for name in VALUES)


@pytest.mark.parametrize("value", ["hourly", "Weekly", "", "none", "yearly"])
def test_any_other_value_on_a_repo_is_refused_naming_the_setting_and_the_four(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="e2e_schedule") as refused:
        repo(e2e_schedule=value)

    assert "Extra inputs" not in str(refused.value)
    assert all(name in str(refused.value) for name in VALUES)


def test_config_show_prints_the_values_set(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = WorkspaceConfig.model_validate(
        {
            "global_limits": {"e2e_schedule": "monthly"},
            "repos": {
                "app": {
                    "path": str(tmp_path / "app"),
                    "slug": "example/app",
                    "tests": {"e2e_schedule": "daily"},
                }
            },
        }
    )
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["global_limits"]["e2e_schedule"] == "monthly"
    assert shown["repos"]["app"]["tests"]["e2e_schedule"] == "daily"


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

    assert yaml.safe_load(capsys.readouterr().out)["global_limits"]["e2e_schedule"] == "weekly"
