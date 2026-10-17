"""`emergency_extra` belongs to `project_limits` alone: another block refuses it without the
migration pointer, and the three settings that did move keep theirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config

MOVED = ("max_units_in_progress", "max_concurrent_stacks", "max_concurrent_restacks")


def load_text(tmp_path: Path, text: str) -> config.WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return config.load(path)


@pytest.mark.parametrize("block", ["global_limits", "limits"])
def test_the_key_in_another_block_names_that_block_and_project_limits(
    tmp_path: Path, block: str
) -> None:
    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, f"version: 1\n{block}:\n  emergency_extra: 2\n")

    message = str(refused.value)
    assert f"{block}.emergency_extra" in message
    assert "project_limits" in message
    assert "--migrate" not in message


def test_only_the_three_settings_that_lived_in_limits_are_moved(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "version: 1\nproject_limits:\n  emergency_extra: 2\n")

    assert loaded.project_limits.emergency_extra == 2
    assert config.MOVED_TO_PROJECT_LIMITS == MOVED


@pytest.mark.parametrize("name", MOVED)
def test_an_old_setting_left_in_global_limits_keeps_its_pointer(tmp_path: Path, name: str) -> None:
    load_text(tmp_path, "version: 1\nproject_limits:\n  emergency_extra: 2\n")

    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, f"version: 1\nglobal_limits:\n  {name}: 3\n")

    message = str(refused.value)
    assert f"global_limits.{name}: moved to project_limits.{name}" in message
    assert "abk config --migrate" in message
