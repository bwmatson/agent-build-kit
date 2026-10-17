"""`project_limits.emergency_extra`: the cap on priority-0 units started past the normal limits."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.cli import main
from agent_build_kit.installation import load_installation


def write(tmp_path: Path, block: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(f"version: 1\nproject_limits:\n{block}")
    return path


def test_a_block_without_the_key_reads_one(tmp_path: Path) -> None:
    path = write(tmp_path, "  max_units_in_progress: 3\n")

    assert config.load(path).project_limits.emergency_extra == 1


@pytest.mark.parametrize("value", [0, 3])
def test_zero_and_a_positive_whole_number_are_accepted(tmp_path: Path, value: int) -> None:
    path = write(tmp_path, f"  emergency_extra: {value}\n")

    assert config.load(path).project_limits.emergency_extra == value


@pytest.mark.parametrize("value", ["-1", "1.5", "many"])
def test_a_bad_value_is_refused_by_name_and_not_as_an_unknown_key(
    tmp_path: Path, value: str
) -> None:
    assert (
        config.load(write(tmp_path, "  emergency_extra: 2\n")).project_limits.emergency_extra == 2
    )

    with pytest.raises(config.ConfigError, match=r"project_limits\.emergency_extra") as refused:
        config.load(write(tmp_path, f"  emergency_extra: {value}\n"))

    assert "Extra inputs" not in str(refused.value)


def test_a_misspelled_key_is_refused_as_an_unknown_key(tmp_path: Path) -> None:
    assert (
        config.load(write(tmp_path, "  emergency_extra: 2\n")).project_limits.emergency_extra == 2
    )

    with pytest.raises(config.ConfigError, match=r"project_limits\.emergency_extras") as refused:
        config.load(write(tmp_path, "  emergency_extra: 2\n  emergency_extras: 3\n"))

    assert "Extra inputs" in str(refused.value)


def test_the_installation_returns_the_value(tmp_path: Path) -> None:
    path = write(tmp_path, "  emergency_extra: 3\n")

    assert load_installation(path).emergency_extra == 3


def test_abk_config_prints_it_among_the_project_limits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "  emergency_extra: 2\n")

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["project_limits"]["emergency_extra"] == 2
