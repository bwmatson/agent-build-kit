"""`project_limits` holds the three scheduling settings, configured once at the root."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config


def load_text(tmp_path: Path, text: str) -> config.WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return config.load(path)


def test_the_defaults_are_five_four_and_two(tmp_path: Path) -> None:
    block = load_text(tmp_path, "version: 1\n").project_limits

    assert block.max_units_in_progress == 5
    assert block.max_concurrent_stacks == 4
    assert block.max_concurrent_restacks == 2


def test_the_settings_are_read_once_for_every_project(tmp_path: Path) -> None:
    loaded = load_text(
        tmp_path,
        "version: 1\n"
        "project_limits:\n  max_units_in_progress: 3\n"
        "repos:\n  app:\n    path: app\n    slug: example/app\n"
        "  platform:\n    path: platform\n    slug: example/platform\n",
    )

    assert loaded.project_limits.max_units_in_progress == 3
    assert loaded.project_limits.max_concurrent_stacks == 4


@pytest.mark.parametrize("setting", ["max_units_in_progress", "max_concurrent_restacks"])
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "many"])
def test_a_value_under_the_minimum_or_of_the_wrong_type_is_refused_by_name(
    tmp_path: Path, setting: str, value: str
) -> None:
    with pytest.raises(config.ConfigError, match=rf"project_limits\.{setting}"):
        load_text(tmp_path, f"version: 1\nproject_limits:\n  {setting}: {value}\n")


def test_a_string_is_refused_for_the_build_workers_by_name(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match=r"project_limits\.max_concurrent_stacks"):
        load_text(tmp_path, "version: 1\nproject_limits:\n  max_concurrent_stacks: many\n")


@pytest.mark.parametrize("key", ["project_limits", "limits"])
def test_a_repo_entry_cannot_override_the_limits(tmp_path: Path, key: str) -> None:
    head = "version: 1\nproject_limits:\n  max_units_in_progress: 3\n"
    repo = "repos:\n  app:\n    path: app\n    slug: example/app\n"
    assert load_text(tmp_path, head + repo).project_limits.max_units_in_progress == 3

    with pytest.raises(config.ConfigError, match=rf"repos\.app\.{key}"):
        load_text(tmp_path, f"{head}{repo}    {key}:\n      max_units_in_progress: 2\n")


def account_block(tmp_path: Path, block: str) -> config.ProjectLimitsConfig:
    """The `project_limits` of the account `kit`, read from the machine's overlay."""
    (tmp_path / "abk.local.yaml").write_text(
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n"
        f"        config_dir: {tmp_path / 'kit-home'}\n        project_limits:\n{block}"
    )
    loaded = load_text(tmp_path, "version: 1\n")
    return loaded.runtimes["claude_code"].accounts["kit"].project_limits


def test_an_account_block_is_the_type_of_the_top_level_block(tmp_path: Path) -> None:
    block = account_block(
        tmp_path,
        "          max_concurrent_stacks: 2\n          max_concurrent_restacks: 1\n"
        "          max_units_in_progress: 3\n          emergency_extra: 0\n",
    )

    assert isinstance(block, config.ProjectLimitsConfig)
    assert block.max_concurrent_stacks == 2
    assert block.max_concurrent_restacks == 1
    assert block.max_units_in_progress == 3
    assert block.emergency_extra == 0


def test_an_account_block_records_the_fields_it_set(tmp_path: Path) -> None:
    block = account_block(tmp_path, "          max_units_in_progress: 3\n")

    assert block.model_fields_set == {"max_units_in_progress"}
    assert block.max_concurrent_stacks == 4


@pytest.mark.parametrize(
    "setting", ["max_units_in_progress", "max_concurrent_restacks", "emergency_extra"]
)
def test_an_account_block_has_the_top_level_bounds(tmp_path: Path, setting: str) -> None:
    below = "-1" if setting == "emergency_extra" else "0"

    with pytest.raises(config.ConfigError, match=rf"project_limits\.{setting}"):
        account_block(tmp_path, f"          {setting}: {below}\n")


def test_an_account_block_refuses_an_unknown_key_by_name(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match=r"project_limits\.max_stacks"):
        account_block(tmp_path, "          max_stacks: 2\n")


def test_an_account_with_no_block_sets_nothing() -> None:
    assert config.AccountConfig().project_limits.model_fields_set == set()
