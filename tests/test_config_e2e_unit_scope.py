"""`e2e_unit_scope` is `own` or `full`: a default under `limits` and an optional override
on a repo's `tests` block, the repo's winning (spec: e2e-scope)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import (
    E2eUnitScope,
    LimitsConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
    e2e_unit_scope,
)


def limits(**given: Any) -> Any:
    return LimitsConfig.model_validate(given)


def repo(**tests: Any) -> Any:
    return RepoConfig.model_validate({"path": "/work/app", "slug": "example/app", "tests": tests})


def test_the_default_is_own() -> None:
    assert limits().e2e_unit_scope == "own"
    assert e2e_unit_scope(repo(), limits()) is E2eUnitScope.OWN


@pytest.mark.parametrize("value", ["own", "full"])
def test_each_value_is_accepted_in_limits_and_on_a_repo(value: str) -> None:
    assert limits(e2e_unit_scope=value).e2e_unit_scope == value
    assert repo(e2e_unit_scope=value).tests.e2e_unit_scope == value


def test_a_repo_has_no_value_of_its_own_by_default() -> None:
    assert repo().tests.e2e_unit_scope is None


def test_the_repos_value_wins_over_limits() -> None:
    assert e2e_unit_scope(repo(e2e_unit_scope="own"), limits(e2e_unit_scope="full")) == "own"
    assert e2e_unit_scope(repo(e2e_unit_scope="full"), limits(e2e_unit_scope="own")) == "full"


def test_a_repo_without_a_value_follows_limits() -> None:
    assert e2e_unit_scope(repo(), limits(e2e_unit_scope="full")) is E2eUnitScope.FULL


@pytest.mark.parametrize("value", ["some", "Full", "", "off", "none"])
def test_any_other_value_in_limits_is_refused_naming_the_setting_and_both_values(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="e2e_unit_scope") as refused:
        limits(e2e_unit_scope=value)

    assert "Extra inputs" not in str(refused.value)
    assert "own" in str(refused.value) and "full" in str(refused.value)


@pytest.mark.parametrize("value", ["some", "Full", "", "off", "none"])
def test_any_other_value_on_a_repo_is_refused_naming_the_setting_and_both_values(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="e2e_unit_scope") as refused:
        repo(e2e_unit_scope=value)

    assert "Extra inputs" not in str(refused.value)
    assert "own" in str(refused.value) and "full" in str(refused.value)


def test_config_show_prints_the_values_set(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = WorkspaceConfig.model_validate(
        {
            "limits": {"e2e_unit_scope": "full"},
            "repos": {
                "app": {
                    "path": str(tmp_path / "app"),
                    "slug": "example/app",
                    "tests": {"e2e_unit_scope": "own"},
                }
            },
        }
    )
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["global_limits"]["e2e_unit_scope"] == "full"
    assert shown["repos"]["app"]["tests"]["e2e_unit_scope"] == "own"
