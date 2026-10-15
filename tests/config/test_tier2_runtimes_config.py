"""`tests.runtimes_blocked`, `runtimes_allowed` and `tier2_runtimes`, at the top of the file
and per repo (spec: tier2-runtime-blocks)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit import runtimes
from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump, tier2_variants
from agent_build_kit.runtimes import known_agents

SETTINGS = ["runtimes_blocked", "runtimes_allowed", "tier2_runtimes"]
KNOWN = sorted({*runtimes.names(), known_agents.RUNTIME_NAME})


def config(
    given: dict[str, Any] | None = None, *, configured: dict[str, Any] | None = None, **tests: Any
) -> Any:
    return WorkspaceConfig.model_validate(
        {
            "tests": {**(given or {}), **tests},
            "runtimes": configured or {},
            "repos": {"app": {"path": "/work/app", "slug": "example/app"}},
        }
    )


def listing(setting: str, names: list[str], *, configured: dict[str, Any] | None = None) -> Any:
    return config({setting: names}, configured=configured)


@pytest.mark.parametrize("setting", SETTINGS)
def test_each_list_defaults_to_empty(setting: str) -> None:
    assert getattr(config().tests, setting) == []


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize("name", KNOWN)
def test_each_list_accepts_the_registry_and_protocol_runtime_names(setting: str, name: str) -> None:
    assert getattr(listing(setting, [name]).tests, setting) == [name]


@pytest.mark.parametrize("setting", SETTINGS)
def test_each_list_accepts_a_runtime_the_file_configures(setting: str) -> None:
    loaded = listing(setting, ["custom"], configured={"custom": {}})

    assert getattr(loaded.tests, setting) == ["custom"]


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize(
    "bad", [["nothing"], ["base"], ["acp", "acp"]], ids=["unknown", "base", "twice"]
)
def test_a_bad_name_is_refused_naming_the_setting_and_the_runtimes_there_are(
    setting: str, bad: list[str]
) -> None:
    with pytest.raises(ValidationError) as refused:
        listing(setting, bad)

    text = str(refused.value)
    assert f"tests.{setting}" in text
    assert all(name in text for name in KNOWN)


def test_a_runtime_in_both_blocked_and_allowed_is_refused_naming_both_settings() -> None:
    with pytest.raises(ValidationError) as refused:
        config(runtimes_blocked=["acp"], runtimes_allowed=["acp"])

    text = str(refused.value)
    assert "tests.runtimes_blocked" in text
    assert "tests.runtimes_allowed" in text


def test_a_configuration_with_only_one_of_them_loads() -> None:
    assert config(runtimes_blocked=["acp"]).tests.runtimes_allowed == []
    assert config(runtimes_allowed=["acp"]).tests.runtimes_blocked == []


def test_a_repo_has_no_tier2_runtimes_of_its_own_by_default() -> None:
    assert config().repos["app"].tests.tier2_runtimes is None


def test_a_repo_with_nothing_set_has_only_the_base_variant() -> None:
    loaded = config()

    assert tier2_variants(loaded.repos["app"], loaded) == ("base",)


def test_the_top_level_list_gives_the_variants_after_base() -> None:
    loaded = config(tier2_runtimes=["acp", "claude_code"])

    assert tier2_variants(loaded.repos["app"], loaded) == ("base", "acp", "claude_code")


def test_a_repo_list_replaces_the_top_level_one() -> None:
    loaded = WorkspaceConfig.model_validate(
        {
            "tests": {"tier2_runtimes": ["acp"]},
            "repos": {
                "app": {
                    "path": "/work/app",
                    "slug": "example/app",
                    "tests": {"tier2_runtimes": ["claude_code"]},
                },
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
        }
    )

    assert tier2_variants(loaded.repos["app"], loaded) == ("base", "claude_code")
    assert tier2_variants(loaded.repos["platform"], loaded) == ("base", "acp")


def test_an_empty_repo_list_is_set_and_runs_only_the_base() -> None:
    loaded = WorkspaceConfig.model_validate(
        {
            "tests": {"tier2_runtimes": ["acp"]},
            "repos": {
                "app": {
                    "path": "/work/app",
                    "slug": "example/app",
                    "tests": {"tier2_runtimes": []},
                }
            },
        }
    )

    assert tier2_variants(loaded.repos["app"], loaded) == ("base",)


def test_a_repo_list_naming_an_unknown_runtime_is_refused_naming_the_setting() -> None:
    with pytest.raises(ValidationError) as refused:
        WorkspaceConfig.model_validate(
            {
                "repos": {
                    "app": {
                        "path": "/work/app",
                        "slug": "example/app",
                        "tests": {"tier2_runtimes": ["nothing"]},
                    }
                }
            }
        )

    text = str(refused.value)
    assert "tests.tier2_runtimes" in text
    assert all(name in text for name in KNOWN)


@pytest.mark.parametrize("setting", SETTINGS)
def test_base_is_refused_even_when_a_runtime_is_configured_under_that_key(setting: str) -> None:
    with pytest.raises(ValidationError, match=f"tests.{setting}"):
        listing(setting, ["base"], configured={"base": {}})


def test_config_show_prints_the_lists_set(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(
        dump(
            WorkspaceConfig.model_validate(
                {
                    "tests": {
                        "runtimes_blocked": ["acp"],
                        "runtimes_allowed": ["claude_code"],
                        "tier2_runtimes": ["acp"],
                    },
                    "repos": {
                        "app": {
                            "path": str(tmp_path / "app"),
                            "slug": "example/app",
                            "tests": {"tier2_runtimes": ["claude_code"]},
                        }
                    },
                }
            )
        )
    )

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["tests"] == {
        "runtimes_blocked": ["acp"],
        "runtimes_allowed": ["claude_code"],
        "tier2_runtimes": ["acp"],
    }
    assert shown["repos"]["app"]["tests"]["tier2_runtimes"] == ["claude_code"]
