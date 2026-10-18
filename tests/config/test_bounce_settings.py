"""`global_limits.bounce_limit` and `bounce_span_seconds`: when a unit counts as looping."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.cli import main


def write(tmp_path: Path, block: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(f"version: 1\nglobal_limits:\n{block}")
    return path


@pytest.mark.parametrize("key, value", [("bounce_limit", 1), ("bounce_span_seconds", 0)])
def test_a_value_below_the_floor_is_refused_by_name(tmp_path: Path, key: str, value: int) -> None:
    with pytest.raises(config.ConfigError, match=rf"global_limits\.{key}"):
        config.load(write(tmp_path, f"  {key}: {value}\n"))


def test_the_defaults_are_three_and_120_and_the_floors_are_two_and_one(tmp_path: Path) -> None:
    limits = config.load(write(tmp_path, "  max_flakes_per_run: 5\n")).global_limits

    assert (limits.bounce_limit, limits.bounce_span_seconds) == (3, 120)
    assert config.load(write(tmp_path, "  bounce_limit: 2\n  bounce_span_seconds: 1\n"))
    with pytest.raises(config.ConfigError):
        config.load(write(tmp_path, "  bounce_limit: 1\n"))


def test_config_show_prints_both(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bad").mkdir()
    path = write(tmp_path, "  bounce_limit: 4\n  bounce_span_seconds: 60\n")

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)["global_limits"]
    assert (shown["bounce_limit"], shown["bounce_span_seconds"]) == (4, 60)
    refused = write(tmp_path / "bad", "  bounce_limit: 1\n")
    assert main(["--config", str(refused), "config", "--show"]) != 0
