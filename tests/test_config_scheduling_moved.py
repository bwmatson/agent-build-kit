"""A scheduling setting left in `global_limits` (or `limits`) is refused with a pointer."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config

MOVED = ["max_units_in_progress", "max_concurrent_stacks", "max_concurrent_restacks"]


def load_text(tmp_path: Path, text: str) -> config.WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return config.load(path)


@pytest.mark.parametrize("name", MOVED)
def test_a_moved_setting_under_global_limits_names_the_key_and_the_way_out(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, f"version: 1\nglobal_limits:\n  {name}: 3\n")

    message = str(refused.value)
    assert f"global_limits.{name}" in message
    assert f"project_limits.{name}" in message
    assert "abk config --migrate" in message


@pytest.mark.parametrize("name", MOVED)
def test_a_moved_setting_under_the_old_key_names_it_as_written(tmp_path: Path, name: str) -> None:
    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, f"version: 1\nlimits:\n  {name}: 3\n")

    message = str(refused.value)
    assert f"limits.{name}" in message
    assert f"global_limits.{name}" not in message
    assert f"project_limits.{name}" in message
    assert "abk config --migrate" in message


def test_the_settings_that_stay_load_from_global_limits(tmp_path: Path) -> None:
    loaded = load_text(
        tmp_path,
        "version: 1\nglobal_limits:\n  max_review_rounds: 5\n"
        "  stack_depth_build_cap: 2\n"
        "project_limits:\n  max_units_in_progress: 3\n",
    )

    block = loaded.global_limits
    assert block.max_review_rounds == 5
    assert block.stack_depth_build_cap == 2
    assert loaded.project_limits.max_units_in_progress == 3
